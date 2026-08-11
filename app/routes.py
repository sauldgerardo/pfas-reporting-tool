"""All Flask routes, grouped in a single blueprint.

Route map
---------
GET  /                      dashboard (metrics + charts)
GET  /sites                 site list, filterable by status/region
POST /sites/new             create a site
POST /sites/<id>/status     mark Complete / Pending / Overdue
POST /sites/<id>/delete     remove a site
GET  /import                Excel import form
POST /import                handle the upload
GET  /reminders             reminder history + send controls
POST /reminders/send        run the reminder engine
GET  /summary               AI summary page
POST /summary               run generate_summary() on pasted text
"""

from datetime import date

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for,
)

from .ai_summary import generate_summary
from .config import Config
from .db import (
    execute, get_metrics, get_region_breakdown, query, refresh_overdue_statuses,
)
from .email_engine import find_sites_needing_reminders, send_reminders
from .excel_import import import_sites_from_excel

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
def dashboard():
    # Re-evaluate overdue state on every load so the numbers are never stale.
    flipped = refresh_overdue_statuses()
    if flipped:
        flash(f"{flipped} pending site(s) passed the deadline and are now Overdue.", "warning")

    metrics = get_metrics()
    regions = get_region_breakdown()

    # Chart.js reads these arrays directly; building them server-side keeps
    # the template free of data munging.
    chart_data = {
        "status_labels": list(Config.STATUSES),
        "status_values": [metrics["complete"], metrics["pending"], metrics["overdue"]],
        "region_labels": [r["region"] for r in regions],
        "region_complete": [r["complete"] for r in regions],
        "region_pending": [r["pending"] for r in regions],
        "region_overdue": [r["overdue"] for r in regions],
        "completion_pct": metrics["completion_pct"],
    }

    recent = query(
        "SELECT r.*, s.site_name FROM reminders r "
        "LEFT JOIN sites s ON s.id = r.site_id "
        "ORDER BY r.sent_at DESC, r.id DESC LIMIT 5"
    )

    return render_template(
        "dashboard.html",
        metrics=metrics,
        regions=regions,
        chart_data=chart_data,
        recent_reminders=recent,
        deadline=Config.DEADLINE,
        year=Config.REPORTING_YEAR,
    )


# ---------------------------------------------------------------------------
# Site management
# ---------------------------------------------------------------------------

@bp.route("/sites")
def sites():
    refresh_overdue_statuses()

    status_filter = request.args.get("status", "").strip()
    region_filter = request.args.get("region", "").strip()

    sql = "SELECT * FROM sites WHERE 1=1"
    params = []
    if status_filter in Config.STATUSES:
        sql += " AND submission_status = ?"
        params.append(status_filter)
    if region_filter:
        sql += " AND COALESCE(NULLIF(TRIM(region), ''), 'Unassigned') = ?"
        params.append(region_filter)
    sql += " ORDER BY site_name ASC"

    rows = query(sql, tuple(params))
    all_regions = [r["region"] for r in get_region_breakdown()]

    return render_template(
        "sites.html",
        sites=rows,
        statuses=Config.STATUSES,
        status_colors=Config.STATUS_COLORS,
        regions=all_regions,
        status_filter=status_filter,
        region_filter=region_filter,
    )


@bp.route("/sites/new", methods=["POST"])
def create_site():
    site_name = request.form.get("site_name", "").strip()
    site_email = request.form.get("site_email", "").strip()

    if not site_name or not site_email:
        flash("Site Name and Email are both required.", "danger")
        return redirect(url_for("main.sites"))

    status = request.form.get("submission_status", "Pending")
    if status not in Config.STATUSES:
        status = "Pending"

    # Marking a site Complete at creation time should also stamp the date.
    last_date = date.today().isoformat() if status == "Complete" else None

    try:
        execute(
            "INSERT INTO sites (site_name, site_lead, site_email, region, "
            "submission_status, last_submission_date) VALUES (?, ?, ?, ?, ?, ?)",
            (
                site_name,
                request.form.get("site_lead", "").strip(),
                site_email,
                request.form.get("region", "").strip(),
                status,
                last_date,
            ),
        )
        flash(f"Added site '{site_name}'.", "success")
    except Exception as exc:  # noqa: BLE001 - most likely the UNIQUE constraint
        flash(f"Could not add '{site_name}': {exc}", "danger")

    return redirect(url_for("main.sites"))


@bp.route("/sites/<int:site_id>/status", methods=["POST"])
def update_status(site_id):
    new_status = request.form.get("submission_status", "")
    if new_status not in Config.STATUSES:
        flash("Unknown status.", "danger")
        return redirect(request.referrer or url_for("main.sites"))

    if new_status == "Complete":
        # Completing a submission records when it landed.
        execute(
            "UPDATE sites SET submission_status = ?, last_submission_date = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (new_status, date.today().isoformat(), site_id),
        )
    else:
        # Reopening clears the submission date - it's no longer complete.
        execute(
            "UPDATE sites SET submission_status = ?, last_submission_date = NULL, "
            "updated_at = datetime('now') WHERE id = ?",
            (new_status, site_id),
        )

    flash(f"Status updated to {new_status}.", "success")
    return redirect(request.referrer or url_for("main.sites"))


@bp.route("/sites/<int:site_id>/delete", methods=["POST"])
def delete_site(site_id):
    execute("DELETE FROM sites WHERE id = ?", (site_id,))
    flash("Site deleted.", "success")
    return redirect(url_for("main.sites"))


# ---------------------------------------------------------------------------
# Excel import
# ---------------------------------------------------------------------------

@bp.route("/import", methods=["GET", "POST"])
def import_excel():
    if request.method == "GET":
        return render_template("import.html", report=None)

    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose an .xlsx file to upload.", "danger")
        return redirect(url_for("main.import_excel"))

    if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Only .xlsx / .xlsm workbooks are supported.", "danger")
        return redirect(url_for("main.import_excel"))

    try:
        # pandas reads the werkzeug FileStorage directly - no temp file needed.
        report = import_sites_from_excel(upload)
    except Exception as exc:  # noqa: BLE001
        flash(f"Could not read the workbook: {exc}", "danger")
        return redirect(url_for("main.import_excel"))

    if report["errors"] and not (report["created"] or report["updated"]):
        flash("Import failed. See details below.", "danger")
    else:
        flash(
            f"Import complete: {report['created']} created, "
            f"{report['updated']} updated, {report['skipped']} skipped.",
            "success",
        )

    return render_template("import.html", report=report)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@bp.route("/reminders")
def reminders():
    refresh_overdue_statuses()

    pending_sites = find_sites_needing_reminders()
    history = query(
        "SELECT r.*, s.site_name FROM reminders r "
        "LEFT JOIN sites s ON s.id = r.site_id "
        "ORDER BY r.sent_at DESC, r.id DESC LIMIT 100"
    )

    return render_template(
        "reminders.html",
        pending_sites=pending_sites,
        history=history,
        dry_run=Config.EMAIL_DRY_RUN,
        status_colors=Config.STATUS_COLORS,
        last_run=None,
    )


@bp.route("/reminders/send", methods=["POST"])
def run_reminders():
    # Checkbox list; empty means "all eligible sites".
    selected = request.form.getlist("site_ids")
    site_ids = [int(s) for s in selected] if selected else None

    # The form can force a dry run even when EMAIL_DRY_RUN=0.
    force_dry = request.form.get("dry_run") == "1"
    dry_run = True if force_dry else None  # None = use the configured default

    report = send_reminders(site_ids=site_ids, dry_run=dry_run)

    if report["eligible"] == 0:
        flash("No sites currently need a reminder.", "info")
    elif report["dry_run"]:
        flash(
            f"DRY RUN: generated {report['sent']} reminder(s). "
            "Nothing was actually emailed. Set EMAIL_DRY_RUN=0 to send for real.",
            "warning",
        )
    else:
        flash(
            f"Sent {report['sent']} reminder(s), {report['failed']} failed.",
            "success" if not report["failed"] else "danger",
        )

    refresh_overdue_statuses()
    history = query(
        "SELECT r.*, s.site_name FROM reminders r "
        "LEFT JOIN sites s ON s.id = r.site_id "
        "ORDER BY r.sent_at DESC, r.id DESC LIMIT 100"
    )

    return render_template(
        "reminders.html",
        pending_sites=find_sites_needing_reminders(),
        history=history,
        dry_run=Config.EMAIL_DRY_RUN,
        status_colors=Config.STATUS_COLORS,
        last_run=report,
    )


# ---------------------------------------------------------------------------
# AI summary
# ---------------------------------------------------------------------------

@bp.route("/summary", methods=["GET", "POST"])
def summary():
    all_sites = query("SELECT id, site_name FROM sites ORDER BY site_name")

    if request.method == "GET":
        return render_template(
            "summary.html",
            sites=all_sites,
            result=None,
            submitted_text="",
            provider=Config.AI_PROVIDER,
            history=query(
                "SELECT sub.*, s.site_name FROM submissions sub "
                "LEFT JOIN sites s ON s.id = sub.site_id "
                "ORDER BY sub.submitted_at DESC, sub.id DESC LIMIT 10"
            ),
        )

    text = request.form.get("submission_text", "")
    site_id = request.form.get("site_id") or None

    result = generate_summary(text)

    # Persist so the team has a record of what was analysed and what came back.
    execute(
        "INSERT INTO submissions (site_id, raw_text, executive_summary, "
        "key_findings, follow_up_required, follow_up_reason, provider) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(site_id) if site_id else None,
            text,
            result["executive_summary"],
            "\n".join(result["key_findings"]),
            result["follow_up_required"],
            result.get("follow_up_reason", ""),
            result.get("provider", Config.AI_PROVIDER),
        ),
    )

    return render_template(
        "summary.html",
        sites=all_sites,
        result=result,
        submitted_text=text,
        selected_site_id=int(site_id) if site_id else None,
        provider=Config.AI_PROVIDER,
        history=query(
            "SELECT sub.*, s.site_name FROM submissions sub "
            "LEFT JOIN sites s ON s.id = sub.site_id "
            "ORDER BY sub.submitted_at DESC, sub.id DESC LIMIT 10"
        ),
    )
