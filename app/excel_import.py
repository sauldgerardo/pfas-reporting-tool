"""Bulk import of sites from an Excel workbook.

Expected sheet columns (header row, case- and space-insensitive):

    SiteName | SiteLead | Email | Region

Optional extra columns, used if present:

    Status | LastSubmissionDate

Import is idempotent: a row whose SiteName already exists updates that site's
contact details rather than creating a duplicate.
"""

import pandas as pd

from .config import Config
from .db import get_db

# Canonical column name -> the header spellings we accept for it.
COLUMN_ALIASES = {
    "site_name": {"sitename", "site name", "site", "name"},
    "site_lead": {"sitelead", "site lead", "lead", "owner", "contact"},
    "site_email": {"email", "siteemail", "site email", "e-mail", "emailaddress"},
    "region": {"region", "area", "geography"},
    "submission_status": {"status", "submissionstatus", "submission status"},
    "last_submission_date": {
        "lastsubmissiondate", "last submission date", "submissiondate", "submitted",
    },
}

REQUIRED = ("site_name", "site_email")


def _normalize(header: str) -> str:
    """Lowercase and strip a header so 'Site Name ' matches 'sitename'."""
    return str(header).strip().lower().replace("_", " ").replace("  ", " ")


def _map_columns(df: pd.DataFrame) -> dict:
    """Map canonical field names to the actual DataFrame column labels."""
    lookup = {}
    for column in df.columns:
        key = _normalize(column)
        compact = key.replace(" ", "")
        for canonical, aliases in COLUMN_ALIASES.items():
            if key in aliases or compact in aliases:
                lookup.setdefault(canonical, column)
                break
    return lookup


def _clean(value) -> str:
    """Turn NaN / None / whitespace into an empty string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def import_sites_from_excel(file_obj_or_path, sheet_name=0) -> dict:
    """Read a workbook and upsert its rows into the sites table.

    Returns a report: {created, updated, skipped, errors[], columns_found}.
    """
    report = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "columns_found": [],
    }

    # openpyxl is the engine pandas uses for .xlsx.
    df = pd.read_excel(file_obj_or_path, sheet_name=sheet_name, engine="openpyxl")

    if df.empty:
        report["errors"].append("The sheet contains no data rows.")
        return report

    columns = _map_columns(df)
    report["columns_found"] = sorted(columns.keys())

    missing = [c for c in REQUIRED if c not in columns]
    if missing:
        report["errors"].append(
            "Missing required column(s): "
            + ", ".join(m.replace("_", " ").title() for m in missing)
            + f". Found headers: {list(df.columns)}"
        )
        return report

    conn = get_db()

    # Excel rows are 1-indexed and row 1 is the header, so data starts at row 2.
    for offset, (_, row) in enumerate(df.iterrows(), start=2):
        site_name = _clean(row[columns["site_name"]])
        site_email = _clean(row[columns["site_email"]])

        if not site_name or not site_email:
            report["skipped"] += 1
            report["errors"].append(
                f"Row {offset}: skipped - SiteName and Email are both required."
            )
            continue

        site_lead = _clean(row[columns["site_lead"]]) if "site_lead" in columns else ""
        region = _clean(row[columns["region"]]) if "region" in columns else ""

        status = "Pending"
        if "submission_status" in columns:
            candidate = _clean(row[columns["submission_status"]]).title()
            if candidate in Config.STATUSES:
                status = candidate

        last_date = None
        if "last_submission_date" in columns:
            raw = row[columns["last_submission_date"]]
            if not pd.isna(raw):
                try:
                    last_date = pd.to_datetime(raw).date().isoformat()
                except (ValueError, TypeError):
                    last_date = None

        existing = conn.execute(
            "SELECT id FROM sites WHERE site_name = ?", (site_name,)
        ).fetchone()

        if existing:
            # Update contact details but leave workflow state alone unless the
            # sheet explicitly carried a status column.
            conn.execute(
                "UPDATE sites SET site_lead = ?, site_email = ?, region = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (site_lead, site_email, region, existing[0]),
            )
            if "submission_status" in columns:
                conn.execute(
                    "UPDATE sites SET submission_status = ?, last_submission_date = ? "
                    "WHERE id = ?",
                    (status, last_date, existing[0]),
                )
            report["updated"] += 1
        else:
            conn.execute(
                "INSERT INTO sites (site_name, site_lead, site_email, region, "
                "submission_status, last_submission_date) VALUES (?, ?, ?, ?, ?, ?)",
                (site_name, site_lead, site_email, region, status, last_date),
            )
            report["created"] += 1

    conn.commit()
    return report
