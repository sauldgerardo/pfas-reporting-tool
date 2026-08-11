"""Entry point.

    python main.py

Starts the Flask dev server on http://127.0.0.1:5000. On first run it also
creates database/pfas.db and seeds six example sites so the dashboard has
something to show.
"""

from app import create_app
from app.config import Config
from app.db import query
from app.seed import seed_demo_sites

app = create_app()

if __name__ == "__main__":
    # Seed only when the table is empty, so a restart never duplicates rows
    # or overwrites real data.
    with app.app_context():
        if not query("SELECT 1 FROM sites LIMIT 1"):
            created = seed_demo_sites()
            print(f"[seed] Inserted {created} demo sites.")

    print(f"[config] Reporting year {Config.REPORTING_YEAR}, deadline {Config.DEADLINE}")
    print(f"[config] Email dry run: {Config.EMAIL_DRY_RUN}  |  AI provider: {Config.AI_PROVIDER}")
    print("[run] http://127.0.0.1:5000")

    app.run(host="127.0.0.1", port=5000, debug=Config.DEBUG)
