"""Demo data so the dashboard isn't empty on a fresh install.

Only runs when the sites table has no rows (see main.py).
"""

from datetime import date, timedelta

from .db import get_db

DEMO_SITES = [
    # (name,        lead,             email,                     region,          status,     days_ago)
    ("Kalamazoo",   "Dana Whitfield", "kalamazoo@example.com",   "North America", "Complete", 12),
    ("Puurs",       "Lieve Maes",     "puurs@example.com",       "Europe",        "Pending",  None),
    ("Dublin",      "Aoife Byrne",    "dublin@example.com",      "Europe",        "Overdue",  None),
    ("Rocky Mount", "Marcus Hale",    "rockymount@example.com",  "North America", "Pending",  None),
    ("Singapore",   "Wei Lin Tan",    "singapore@example.com",   "APAC",          "Complete", 30),
    ("Freiburg",    "Jonas Keller",   "freiburg@example.com",    "Europe",        "Overdue",  None),
]


def seed_demo_sites() -> int:
    """Insert the demo rows. Returns how many were created."""
    conn = get_db()
    created = 0

    for name, lead, email, region, status, days_ago in DEMO_SITES:
        submitted = (
            (date.today() - timedelta(days=days_ago)).isoformat()
            if days_ago is not None
            else None
        )
        # A couple of the overdue sites have already been chased once.
        reminder_count = 1 if status == "Overdue" else 0

        conn.execute(
            "INSERT OR IGNORE INTO sites (site_name, site_lead, site_email, region, "
            "submission_status, last_submission_date, reminder_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, lead, email, region, status, submitted, reminder_count),
        )
        created += 1

    conn.commit()
    return created
