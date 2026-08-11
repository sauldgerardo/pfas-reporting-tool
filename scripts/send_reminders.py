"""Standalone reminder runner - the piece you'd put on a cron/Task Scheduler.

Usage (from the project root):

    python scripts/send_reminders.py              # honours EMAIL_DRY_RUN
    python scripts/send_reminders.py --dry-run    # force dry run
    python scripts/send_reminders.py --send       # force real send
    python scripts/send_reminders.py --list       # show who would be emailed

It reuses the exact same engine the web UI calls, so the two can never drift.
"""

import argparse
import sys
from pathlib import Path

# Allow `python scripts/send_reminders.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                    # noqa: E402
from app.db import refresh_overdue_statuses                   # noqa: E402
from app.email_engine import find_sites_needing_reminders, send_reminders  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send PFAS reporting reminders.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true",
                       help="Generate and log reminders without emailing.")
    group.add_argument("--send", action="store_true",
                       help="Actually send, overriding EMAIL_DRY_RUN.")
    parser.add_argument("--list", action="store_true",
                        help="List eligible sites and exit without sending.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        flipped = refresh_overdue_statuses()
        if flipped:
            print(f"Flagged {flipped} site(s) as Overdue (past deadline).")

        if args.list:
            sites = find_sites_needing_reminders()
            if not sites:
                print("No sites need a reminder.")
                return 0
            print(f"{len(sites)} site(s) need a reminder:")
            for site in sites:
                print(f"  [{site['submission_status']:<8}] {site['site_name']:<14} "
                      f"{site['site_email']}  (reminders sent: {site['reminder_count']})")
            return 0

        # None means "use the configured default".
        dry_run = True if args.dry_run else (False if args.send else None)
        report = send_reminders(dry_run=dry_run)

        mode = "DRY RUN" if report["dry_run"] else "LIVE"
        print(f"[{mode}] eligible={report['eligible']} "
              f"processed={report['sent']} failed={report['failed']}")
        for detail in report["details"]:
            marker = "ok " if detail["status"] != "failed" else "ERR"
            print(f"  {marker} {detail['site_name']:<14} -> {detail['recipient']}"
                  + (f"   {detail['error']}" if detail["error"] else ""))

        return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
