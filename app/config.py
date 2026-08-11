"""Central configuration.

Everything is read from environment variables (or a .env file) with a working
default, so `python main.py` succeeds on a clean checkout with no setup.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Project root = the directory containing main.py
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present. override=False means real environment variables
# (e.g. set by a CI runner or systemd unit) win over the file.
load_dotenv(BASE_DIR / ".env", override=False)


def _bool(name: str, default: bool) -> bool:
    """Read a boolean env var. Accepts 1/true/yes/on in any casing."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # --- Flask ---
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-not-for-production")
    DEBUG = _bool("FLASK_DEBUG", True)

    # --- Storage ---
    DATABASE_PATH = BASE_DIR / "database" / "pfas.db"
    SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

    # --- Reporting cycle ---
    REPORTING_YEAR = _int("PFAS_REPORTING_YEAR", date.today().year)
    # Sites still Pending after this date get auto-flagged Overdue on each page
    # load. Defaults to year-end so a fresh install shows all three states;
    # set PFAS_DEADLINE to a past date in .env to watch the auto-flag fire.
    DEADLINE = os.getenv("PFAS_DEADLINE", f"{REPORTING_YEAR}-12-31")

    # --- Email ---
    # Dry run defaults to True on purpose: a proof-of-concept should never
    # accidentally mail real site leads on someone's first run.
    EMAIL_DRY_RUN = _bool("EMAIL_DRY_RUN", True)
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    EMAIL_FROM = os.getenv("EMAIL_FROM", "pfas-reporting@example.com")

    # --- AI summary backend ---
    # 'placeholder' (default) needs no credentials. See app/ai_summary.py.
    AI_PROVIDER = os.getenv("AI_PROVIDER", "placeholder").strip().lower()
    AI_MODEL = os.getenv("AI_MODEL", "")

    # --- Upload handling ---
    UPLOAD_DIR = BASE_DIR / "database" / "uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB cap on Excel uploads

    # --- UI ---
    STATUS_COLORS = {
        "Complete": "success",  # green
        "Pending": "warning",   # yellow
        "Overdue": "danger",    # red
    }
    STATUSES = ("Complete", "Pending", "Overdue")
