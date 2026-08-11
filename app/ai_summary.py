"""AI summarization of a free-text PFAS site submission.

The public entry point is:

    generate_summary(text) -> dict with keys:
        executive_summary   str
        key_findings        list[str]
        follow_up_required  "Yes" | "No"
        follow_up_reason    str
        provider            str   (which backend produced this)

Two backends ship here:

  * "placeholder" (default) - deterministic, rule-based, no network, no API key.
    Good enough to demo the workflow end to end.
  * "api" - a real LLM API call. The implementation is written out below but
    commented; uncomment it and install the SDK to enable.

Swap backends with the AI_PROVIDER environment variable. Adding a third
provider means writing one `_summarize_x(text) -> dict` function and adding a
line to the _PROVIDERS registry at the bottom - no caller changes.
"""

import re

from .config import Config

# Terms that suggest PFAS was actually detected rather than merely discussed.
_PRESENCE_TERMS = (
    "pfas present", "pfas detected", "detected", "presence of pfas",
    "contains pfas", "pfas is used", "pfas are used", "above threshold",
    "exceed", "exceeded", "exceeds", "positive result",
)

# Terms that suggest the site has controls in place already.
_MITIGATION_TERMS = (
    "mitigation", "remediation", "controls", "abatement", "filtration",
    "containment", "substitution", "phase-out", "phase out", "eliminated",
    "treatment",
)

# Terms that signal an open item somebody has to chase.
_OPEN_ITEM_TERMS = (
    "pending", "outstanding", "not yet", "awaiting", "in progress",
    "planned", "scheduled", "to be determined", "tbd", "unknown",
    "further testing", "additional testing", "no data", "incomplete",
)

# Terms that mean testing has actually happened.
_TESTING_TERMS = (
    "testing completed", "test completed", "sampling completed", "tested",
    "analysis completed", "lab results", "results received",
)


def _sentences(text: str) -> list[str]:
    """Split into sentences. Deliberately simple - this is a heuristic pass."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _contains_any(haystack: str, needles) -> list[str]:
    """Return every needle present in haystack (already lowercased)."""
    return [n for n in needles if n in haystack]


def _summarize_placeholder(text: str) -> dict:
    """Rule-based stand-in for a real LLM.

    Produces the same output shape as the API backend so the rest of the
    app is completely unaware of which one ran.
    """
    lowered = text.lower()
    sentences = _sentences(text)

    pfas_present = bool(_contains_any(lowered, _PRESENCE_TERMS))
    has_mitigation = bool(_contains_any(lowered, _MITIGATION_TERMS))
    has_testing = bool(_contains_any(lowered, _TESTING_TERMS))
    open_items = _contains_any(lowered, _OPEN_ITEM_TERMS)

    # --- Executive summary: one paragraph stitched from what we detected. ---
    lead = (
        "The submission reports PFAS presence in site operations."
        if pfas_present
        else "The submission does not report confirmed PFAS presence."
    )
    testing_clause = (
        " Testing activity is documented."
        if has_testing
        else " No completed testing is documented."
    )
    mitigation_clause = (
        " Mitigation or control measures are described as active."
        if has_mitigation
        else " No mitigation or control measures are described."
    )
    executive_summary = (
        f"{lead}{testing_clause}{mitigation_clause} "
        f"Submission length: {len(sentences)} statement(s), "
        f"{len(text.split())} words."
    )

    # --- Key findings: the substantive sentences, capped so the UI stays readable. ---
    key_findings = []
    for sentence in sentences:
        s = sentence.lower()
        if any(
            term in s
            for term in _PRESENCE_TERMS + _MITIGATION_TERMS
            + _OPEN_ITEM_TERMS + _TESTING_TERMS
        ):
            key_findings.append(sentence.rstrip("."))
    if not key_findings:
        # Nothing matched a keyword - fall back to the first few sentences so
        # the reviewer still sees something rather than an empty panel.
        key_findings = [s.rstrip(".") for s in sentences[:3]]
    key_findings = key_findings[:6]

    # --- Follow-up decision + the reason for it. ---
    reasons = []
    if pfas_present and not has_mitigation:
        reasons.append("PFAS reported present with no mitigation described")
    if pfas_present and not has_testing:
        reasons.append("PFAS reported present with no completed testing on record")
    if open_items:
        reasons.append(
            "open items flagged in the text: " + ", ".join(sorted(set(open_items)))
        )
    if not sentences:
        reasons.append("submission is empty")

    follow_up_required = "Yes" if reasons else "No"
    follow_up_reason = (
        "; ".join(reasons).capitalize()
        if reasons
        else "PFAS status, testing, and mitigation are all accounted for."
    )

    return {
        "executive_summary": executive_summary,
        "key_findings": key_findings,
        "follow_up_required": follow_up_required,
        "follow_up_reason": follow_up_reason,
        "provider": "placeholder",
    }


# ---------------------------------------------------------------------------
# Real AI backend - LLM API
# ---------------------------------------------------------------------------
#
# To enable:
#   1. pip install anthropic
#   2. export ANTHROPIC_API_KEY=...
#   3. set AI_PROVIDER=api and AI_MODEL=<model id> in your .env
#   4. uncomment the body of _summarize_api below.
#
# The request uses structured outputs (output_config.format) so the model is
# constrained to return exactly the JSON shape this app expects - no parsing
# heuristics, no retry-on-bad-JSON loop.

_SYSTEM_PROMPT = (
    "You are an environmental compliance analyst reviewing annual PFAS "
    "(per- and polyfluoroalkyl substances) reporting submissions from "
    "manufacturing sites. Summarize the submission factually. Do not infer "
    "facts the text does not state. If the submission leaves a required "
    "element unaddressed - PFAS presence, testing status, or mitigation - "
    "treat that gap as requiring follow-up."
)

# JSON Schema the model's response is constrained to.
_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "Two to four sentences a compliance manager can read at a glance.",
        },
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Discrete factual findings drawn from the submission.",
        },
        "follow_up_required": {
            "type": "string",
            "enum": ["Yes", "No"],
            "description": "Yes if the site needs to be contacted before this submission can be accepted.",
        },
        "follow_up_reason": {
            "type": "string",
            "description": "Why follow-up is or is not required.",
        },
    },
    "required": [
        "executive_summary",
        "key_findings",
        "follow_up_required",
        "follow_up_reason",
    ],
    "additionalProperties": False,
}


def _summarize_api(text: str) -> dict:
    """Summarize via the LLM API. Requires the provider SDK to be installed."""
    # --- BEGIN real implementation (uncomment to enable) ---------------------
    #
    # import json
    # import anthropic
    #
    # # Credentials resolve from the environment - do not hardcode a key.
    # client = anthropic.Anthropic()
    #
    # response = client.messages.create(
    #     model=Config.AI_MODEL,
    #     max_tokens=2000,
    #     system=_SYSTEM_PROMPT,
    #     output_config={
    #         "format": {"type": "json_schema", "schema": _SUMMARY_SCHEMA},
    #         # This is a short extraction task - low effort keeps it fast/cheap.
    #         "effort": "low",
    #     },
    #     messages=[{
    #         "role": "user",
    #         "content": (
    #             "Summarize the following PFAS site submission.\n\n"
    #             f"<submission>\n{text}\n</submission>"
    #         ),
    #     }],
    # )
    #
    # # Safety classifiers can decline a request; check before reading content.
    # if response.stop_reason == "refusal":
    #     raise RuntimeError("Model declined to summarize this submission.")
    #
    # # output_config.format guarantees the first text block is valid JSON
    # # matching _SUMMARY_SCHEMA.
    # raw = next(b.text for b in response.content if b.type == "text")
    # data = json.loads(raw)
    # data["provider"] = "api"
    # return data
    #
    # --- END real implementation --------------------------------------------

    raise NotImplementedError(
        "The API backend is stubbed out. Install the SDK "
        "(`pip install anthropic`), set ANTHROPIC_API_KEY, and uncomment the "
        "implementation block in app/ai_summary.py:_summarize_api()."
    )


# Registry: provider name -> function. Add a backend by adding a line here.
_PROVIDERS = {
    "placeholder": _summarize_placeholder,
    "api": _summarize_api,
}


def generate_summary(text: str) -> dict:
    """Summarize a PFAS site submission.

    Dispatches to whichever backend AI_PROVIDER names. If the configured
    backend fails for any reason, falls back to the placeholder so the UI
    always renders something and the error is surfaced rather than 500-ing.
    """
    if not text or not text.strip():
        return {
            "executive_summary": "No submission text was provided.",
            "key_findings": [],
            "follow_up_required": "Yes",
            "follow_up_reason": "Submission is empty; nothing to review.",
            "provider": Config.AI_PROVIDER,
        }

    provider = Config.AI_PROVIDER
    backend = _PROVIDERS.get(provider, _summarize_placeholder)

    try:
        return backend(text)
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all for the PoC
        result = _summarize_placeholder(text)
        result["provider"] = f"placeholder (fallback from '{provider}': {exc})"
        return result
