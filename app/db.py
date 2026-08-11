"""SQLite access layer.

Uses Flask's request-scoped `g` object so each request gets exactly one
connection, closed automatically when the request ends.
"""

import sqlite3
from datetime import date

from flask import current_app, g

from .config import Config


def get_db() -> sqlite3.Connection:
    """Return the connection for this request, opening one if needed."""
    if "db" not in g:
        Config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            Config.DATABASE_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        # Rows behave like dicts: row["site_name"] instead of row[1].
        conn.row_factory = sqlite3.Row
        # SQLite does not enforce foreign keys unless you ask it to.
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(exception=None) -> None:
    """Teardown hook registered on the app in app/__init__.py."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app=None) -> None:
    """Create the schema if it doesn't exist yet.

    Called once at startup. Safe to call repeatedly — every statement in
    schema.sql is `IF NOT EXISTS`.
    """
    Config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = Config.SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(Config.DATABASE_PATH)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params=(), one: bool = False):
    """Run a SELECT. Returns a list of rows, or a single row when one=True."""
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, params=()) -> int:
    """Run an INSERT/UPDATE/DELETE and commit. Returns lastrowid."""
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def refresh_overdue_statuses() -> int:
    """Flip 'Pending' -> 'Overdue' for anything past the reporting deadline.

    Called at the top of the dashboard and site list so the status a user sees
    is always current, without needing a background scheduler for the PoC.
    Returns the number of rows changed.
    """
    if date.today().isoformat() <= Config.DEADLINE:
        return 0  # deadline not reached yet, nothing to do

    conn = get_db()
    cur = conn.execute(
        "UPDATE sites SET submission_status = 'Overdue', "
        "updated_at = datetime('now') WHERE submission_status = 'Pending'"
    )
    conn.commit()
    changed = cur.rowcount
    cur.close()
    return changed


def get_metrics() -> dict:
    """Headline counts + completion percentage for the dashboard tiles."""
    rows = query(
        "SELECT submission_status AS status, COUNT(*) AS n "
        "FROM sites GROUP BY submission_status"
    )
    counts = {status: 0 for status in Config.STATUSES}
    for row in rows:
        counts[row["status"]] = row["n"]

    total = sum(counts.values())
    complete = counts["Complete"]
    return {
        "total": total,
        "complete": complete,
        "pending": counts["Pending"],
        "overdue": counts["Overdue"],
        # Guard against ZeroDivisionError on an empty database.
        "completion_pct": round(complete / total * 100, 1) if total else 0.0,
    }


def get_region_breakdown() -> list[dict]:
    """Sites per region, split by status - feeds the stacked region chart."""
    rows = query(
        """
        SELECT COALESCE(NULLIF(TRIM(region), ''), 'Unassigned') AS region,
               SUM(submission_status = 'Complete') AS complete,
               SUM(submission_status = 'Pending')  AS pending,
               SUM(submission_status = 'Overdue')  AS overdue,
               COUNT(*)                            AS total
        FROM sites
        GROUP BY region
        ORDER BY total DESC, region ASC
        """
    )
    return [dict(row) for row in rows]
