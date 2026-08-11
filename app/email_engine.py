"""Automated reminder engine.

Finds every site whose submission is still Pending or Overdue, renders a
reminder email for it, sends it (or logs it as a dry run), records the send in
the `reminders` table, and bumps the site's reminder_count.

Dry run is the default. With EMAIL_DRY_RUN=1 the engine does everything
except hand the message to an SMTP server - so you can demo the workflow and
inspect the generated emails without mailing anyone.
"""

import smtplib
from email.message import EmailMessage

from .config import Config
from .db import execute, get_db, query

# Statuses that earn a reminder. Complete sites are left alone.
REMINDABLE_STATUSES = ("Pending", "Overdue")

SUBJECT_TEMPLATE = "PFAS Annual Reporting Reminder"

BODY_TEMPLATE = """Hello{lead_greeting},

This is a reminder that your annual PFAS reporting submission is still outstanding.

Site:      {site_name}
Region:    {region}
Status:    {status}
Deadline:  {deadline}

Please complete your submission.

Thank you.

--
{sender}
Reminder #{reminder_number} for reporting year {year}
"""


def render_reminder(site) -> tuple[str, str]:
    """Build (subject, body) for one site row. Pure function - easy to test."""
    lead = (site["site_lead"] or "").strip()
    body = BODY_TEMPLATE.format(
        lead_greeting=f" {lead}" if lead else "",
        site_name=site["site_name"],
        region=site["region"] or "Unassigned",
        status=site["submission_status"],
        deadline=Config.DEADLINE,
        sender=Config.EMAIL_FROM,
        # This send will be the Nth, so display count+1.
        reminder_number=site["reminder_count"] + 1,
        year=Config.REPORTING_YEAR,
    )
    return SUBJECT_TEMPLATE, body


def _open_smtp():
    """Connect and authenticate. Caller is responsible for closing."""
    server = smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=30)
    if Config.SMTP_USE_TLS:
        server.starttls()
    if Config.SMTP_USERNAME:
        server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
    return server


def _deliver(server, recipient: str, subject: str, body: str) -> None:
    """Send one message over an already-open SMTP connection."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Config.EMAIL_FROM
    msg["To"] = recipient
    msg.set_content(body)
    server.send_message(msg)


def _log_reminder(site_id, recipient, subject, body, status, error=None) -> None:
    """Write the audit row and bump the site's counter in one transaction."""
    conn = get_db()
    conn.execute(
        "INSERT INTO reminders (site_id, recipient, subject, body, status, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (site_id, recipient, subject, body, status, error),
    )
    # A failed send is still an attempt, but only count deliveries the site
    # could actually have received.
    if status in ("sent", "dry_run"):
        conn.execute(
            "UPDATE sites SET reminder_count = reminder_count + 1, "
            "updated_at = datetime('now') WHERE id = ?",
            (site_id,),
        )
    conn.commit()


def find_sites_needing_reminders(site_ids=None) -> list:
    """Sites eligible for a reminder, optionally narrowed to specific IDs."""
    placeholders = ", ".join("?" for _ in REMINDABLE_STATUSES)
    sql = (
        f"SELECT * FROM sites WHERE submission_status IN ({placeholders})"
    )
    params = list(REMINDABLE_STATUSES)

    if site_ids:
        sql += " AND id IN (" + ", ".join("?" for _ in site_ids) + ")"
        params.extend(site_ids)

    sql += " ORDER BY submission_status DESC, site_name ASC"
    return query(sql, tuple(params))


def send_reminders(site_ids=None, dry_run=None) -> dict:
    """Generate and send reminders.

    Args:
        site_ids: restrict to these site IDs. None = every eligible site.
        dry_run:  override Config.EMAIL_DRY_RUN for this call.

    Returns a report dict: counts plus a per-site detail list.
    """
    dry_run = Config.EMAIL_DRY_RUN if dry_run is None else dry_run
    sites = find_sites_needing_reminders(site_ids)

    report = {
        "dry_run": dry_run,
        "eligible": len(sites),
        "sent": 0,
        "failed": 0,
        "details": [],
    }

    if not sites:
        return report

    # Open one SMTP connection for the whole batch rather than reconnecting
    # per site. Skipped entirely in dry run.
    server = None
    connection_error = None
    if not dry_run:
        try:
            server = _open_smtp()
        except Exception as exc:  # noqa: BLE001
            connection_error = f"SMTP connection failed: {exc}"

    try:
        for site in sites:
            subject, body = render_reminder(site)
            recipient = site["site_email"]

            if dry_run:
                status, error = "dry_run", None
            elif connection_error:
                status, error = "failed", connection_error
            else:
                try:
                    _deliver(server, recipient, subject, body)
                    status, error = "sent", None
                except Exception as exc:  # noqa: BLE001
                    status, error = "failed", str(exc)

            _log_reminder(site["id"], recipient, subject, body, status, error)

            if status == "failed":
                report["failed"] += 1
            else:
                report["sent"] += 1

            report["details"].append({
                "site_id": site["id"],
                "site_name": site["site_name"],
                "recipient": recipient,
                "status": status,
                "error": error,
                "subject": subject,
                "body": body,
            })
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 - already done sending
                pass

    return report
