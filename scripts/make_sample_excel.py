"""Generate a sample import workbook you can feed to the /import page.

    python scripts/make_sample_excel.py

Writes database/sample_sites.xlsx with the expected column headers.
"""

import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT = BASE_DIR / "database" / "sample_sites.xlsx"

ROWS = [
    ("Kalamazoo",    "Dana Whitfield", "kalamazoo@example.com",   "North America"),
    ("Puurs",        "Lieve Maes",     "puurs@example.com",       "Europe"),
    ("Dublin",       "Aoife Byrne",    "dublin@example.com",      "Europe"),
    ("Rocky Mount",  "Marcus Hale",    "rockymount@example.com",  "North America"),
    ("Singapore",    "Wei Lin Tan",    "singapore@example.com",   "APAC"),
    ("Freiburg",     "Jonas Keller",   "freiburg@example.com",    "Europe"),
    ("Sao Paulo",    "Beatriz Rocha",  "saopaulo@example.com",    "LATAM"),
    ("Suzhou",       "Chen Yu",        "suzhou@example.com",      "APAC"),
]


def main() -> int:
    df = pd.DataFrame(ROWS, columns=["SiteName", "SiteLead", "Email", "Region"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(OUTPUT, index=False, sheet_name="Sites", engine="openpyxl")
    print(f"Wrote {len(df)} rows to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
