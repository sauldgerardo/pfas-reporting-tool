# PFAS Reporting Automation Tool

A proof-of-concept internal tool that automates annual PFAS reporting data
collection across multiple manufacturing sites.

**The manual process it replaces:**

| Today | With this tool |
|---|---|
| Team manually emails each site | Reminder engine emails every Pending/Overdue site in one run |
| Team tracks responses in Excel | SQLite database + live dashboard |
| Team manually chases missing submissions | Automatic overdue flagging + reminder history per site |
| Team manually writes summary reports | `generate_summary()` produces an executive summary, key findings, and a follow-up flag |

---

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Open <http://127.0.0.1:5000>.

On first run the app creates `database/pfas.db` from `database/schema.sql` and
seeds six demo sites (2 Complete / 2 Pending / 2 Overdue) so the dashboard has
something to show. Delete `database/pfas.db` any time to start over.

**No configuration is required to run.** Email sending defaults to dry run and
the AI summary defaults to a local rule-based backend, so nothing leaves the
machine and no API key is needed.

---

## Project structure

```
pfas-reporting-tool/
├── main.py                     Entry point — creates the app, seeds, serves
├── requirements.txt
├── README.md
├── .env.example                Copy to .env to override any default
│
├── app/
│   ├── __init__.py             Flask application factory
│   ├── config.py               All settings, read from env with safe defaults
│   ├── db.py                   SQLite connection handling + metric queries
│   ├── routes.py               Every HTTP route (one blueprint)
│   ├── excel_import.py         Excel → SQLite upsert
│   ├── email_engine.py         Reminder generation, SMTP delivery, audit log
│   ├── ai_summary.py           generate_summary() + pluggable backends
│   └── seed.py                 Demo data for a fresh install
│
├── database/
│   ├── schema.sql              Full SQL schema (3 tables)
│   └── pfas.db                 Created on first run (git-ignored)
│
├── templates/                  Jinja2 + Bootstrap 5
│   ├── base.html               Nav, flash messages, CDN includes
│   ├── dashboard.html          Metrics, charts, recent activity
│   ├── sites.html              Site list, filters, add/edit/delete
│   ├── import.html             Excel upload + result report
│   ├── reminders.html          Send controls, previews, history
│   └── summary.html            AI summary page
│
├── static/css/style.css        Small layer on top of Bootstrap
│
└── scripts/
    ├── send_reminders.py       CLI reminder runner (for cron/Task Scheduler)
    └── make_sample_excel.py    Generates a valid import workbook
```

---

## Database schema

Three tables (`database/schema.sql`):

### `sites` — one row per manufacturing site

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Site ID |
| `site_name` | TEXT NOT NULL UNIQUE | Uniqueness is what makes Excel import idempotent |
| `site_lead` | TEXT | |
| `site_email` | TEXT NOT NULL | Reminder recipient |
| `region` | TEXT | |
| `submission_status` | TEXT | `CHECK` constrained to Complete / Pending / Overdue |
| `last_submission_date` | TEXT | Stamped when marked Complete, cleared when reopened |
| `reminder_count` | INTEGER | Incremented by the reminder engine |
| `created_at`, `updated_at` | TEXT | |

### `reminders` — audit log of every reminder generated

`id`, `site_id` (FK, cascade delete), `sent_at`, `recipient`, `subject`, `body`,
`status` (`sent` / `dry_run` / `failed`), `error_message`.

Kept separate from `sites` so full history survives after a site goes Complete
and its `reminder_count` stops moving.

### `submissions` — narrative text plus its AI summary

`id`, `site_id` (FK, nullable), `submitted_at`, `raw_text`,
`executive_summary`, `key_findings`, `follow_up_required`, `follow_up_reason`,
`provider`.

---

## Features

### 1. Dashboard (`/`)

- **Metric tiles:** Total / Complete / Pending / Overdue
- **Completion percentage** progress bar
- **Charts** (Chart.js): status-breakdown doughnut, stacked sites-by-region bar
- **Regional detail table** and recent reminder activity
- **Colour coding throughout:** green = Complete, yellow = Pending, red = Overdue

Every page load re-evaluates overdue status: any site still `Pending` after
`PFAS_DEADLINE` is flipped to `Overdue` automatically. No scheduler needed for
the PoC.

### 2. Site management (`/sites`)

List with status/region filters, inline status changes, add, and delete.
Marking a site **Complete** stamps `last_submission_date` with today; moving it
back to Pending or Overdue clears that date.

### 3. Excel import (`/import`)

Expected columns — matched case- and space-insensitively, so `Site Name`,
`sitename`, and `SITENAME` all work:

| SiteName | SiteLead | Email | Region |
|---|---|---|---|
| Kalamazoo | Dana Whitfield | kalamazoo@example.com | North America |
| Puurs | Lieve Maes | puurs@example.com | Europe |
| Dublin | Aoife Byrne | dublin@example.com | Europe |

- **Required:** `SiteName`, `Email`
- **Optional:** `SiteLead`, `Region`, `Status`, `LastSubmissionDate`
- **Idempotent:** a row whose `SiteName` already exists updates that site
  instead of creating a duplicate
- Returns a per-row report: created / updated / skipped / issues

Generate a valid sample file:

```bash
python scripts/make_sample_excel.py     # writes database/sample_sites.xlsx
```

### 4. Automated reminder engine (`/reminders`)

Finds every site whose status is `Pending` or `Overdue`, renders a reminder,
delivers it over SMTP, logs it to the `reminders` table, and increments
`reminder_count`. Complete sites are skipped.

You can send to all eligible sites or tick specific ones. Every generated email
is previewable in the UI before and after the run.

**From the command line** (the piece you'd put on cron / Windows Task
Scheduler — it calls the same engine as the web UI, so the two cannot drift):

```bash
python scripts/send_reminders.py --list      # who would be emailed
python scripts/send_reminders.py --dry-run   # generate + log, don't send
python scripts/send_reminders.py --send      # actually send
python scripts/send_reminders.py             # honour EMAIL_DRY_RUN
```

**Email template:**

```
Subject: PFAS Annual Reporting Reminder

Hello <Site Lead>,

This is a reminder that your annual PFAS reporting submission is still outstanding.

Site:      <Site Name>
Region:    <Region>
Status:    <Pending | Overdue>
Deadline:  <PFAS_DEADLINE>

Please complete your submission.

Thank you.
```

> **Dry run is the default.** With `EMAIL_DRY_RUN=1` the engine does everything
> except hand the message to an SMTP server. A proof of concept should never
> accidentally mail real site leads on someone's first run. Set
> `EMAIL_DRY_RUN=0` and fill in the SMTP settings to send for real.

### 5. Submission tracking

Status is set from the site list. Completing a submission records the date; the
dashboard metrics and charts recompute on the next load.

### 6. AI summary (`/summary`)

Paste a site's submission text and get back:

- **Executive Summary**
- **Key Findings**
- **Follow-Up Required (Yes/No)** — plus the reason for the verdict

Example input:

> "PFAS present in manufacturing process. Testing completed March 2026.
> Mitigation procedures active."

Every analysis is stored in the `submissions` table so the team has a record of
what was reviewed and what came back.

---

## Plugging in a real AI model

`generate_summary(text)` in `app/ai_summary.py` returns:

```python
{
    "executive_summary":  str,
    "key_findings":       list[str],
    "follow_up_required": "Yes" | "No",
    "follow_up_reason":   str,
    "provider":           str,
}
```

It dispatches to a backend chosen by the `AI_PROVIDER` environment variable:

| `AI_PROVIDER` | Backend |
|---|---|
| `placeholder` *(default)* | Rule-based keyword analysis. No network, no API key. |
| `api` | Real LLM API call. Implementation is written out and commented in `_summarize_api()`. |

**To enable the API backend:**

1. `pip install anthropic`
2. `set ANTHROPIC_API_KEY=...`
3. Uncomment the implementation block inside `_summarize_api()` in
   `app/ai_summary.py`
4. Set `AI_PROVIDER=api` and `AI_MODEL=<model id>` in `.env`

That implementation uses **structured outputs**
(`output_config.format` + a JSON Schema), so the model is constrained to return
exactly the dict shape above — no JSON parsing heuristics and no
retry-on-bad-output loop.

**To add any other provider** (Copilot, Azure OpenAI, a local model): write one
function `_summarize_x(text) -> dict` returning the same shape and add a line to
the `_PROVIDERS` registry at the bottom of the file. No caller changes.

If a configured backend raises, `generate_summary()` falls back to the
placeholder and reports the error in the `provider` field rather than 500-ing
the page.

---

## Configuration

Copy `.env.example` to `.env` and edit. Everything has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev key | Flask session signing |
| `FLASK_DEBUG` | `1` | Auto-reload + tracebacks |
| `PFAS_REPORTING_YEAR` | current year | Shown in the UI and email footer |
| `PFAS_DEADLINE` | `<year>-12-31` | Pending sites past this date become Overdue |
| `EMAIL_DRY_RUN` | `1` | `1` = generate + log only; `0` = actually send |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.example.com` / `587` | Mail server |
| `SMTP_USE_TLS` | `1` | STARTTLS |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | empty | Auth (skipped if username is blank) |
| `EMAIL_FROM` | `pfas-reporting@example.com` | Sender address |
| `AI_PROVIDER` | `placeholder` | `placeholder` or `api` |
| `AI_MODEL` | empty | Model ID for the API backend |
| `ANTHROPIC_API_KEY` | empty | Only needed when `AI_PROVIDER=api` |

---

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/sites` | Site list (`?status=`, `?region=`) |
| POST | `/sites/new` | Create a site |
| POST | `/sites/<id>/status` | Change submission status |
| POST | `/sites/<id>/delete` | Delete a site |
| GET/POST | `/import` | Excel import form / upload handler |
| GET | `/reminders` | Eligible sites + reminder history |
| POST | `/reminders/send` | Run the reminder engine |
| GET/POST | `/summary` | AI summary form / run `generate_summary()` |

---

## Known limitations (it's a proof of concept)

- **No authentication.** Anyone who can reach the port has full access. Put it
  behind SSO or a reverse proxy before anyone outside the team touches it.
- **Flask development server.** Use a production WSGI server (waitress, gunicorn)
  for anything beyond a demo.
- **SQLite.** Fine for hundreds of sites and a single writer; move to Postgres if
  multiple people will edit concurrently.
- **Bootstrap and Chart.js load from CDN**, so the first page load needs internet.
  Vendor them locally if this has to run air-gapped.
- **Overdue flagging is lazy**, evaluated on page load rather than by a scheduler.
  For unattended operation, run `scripts/send_reminders.py` on a schedule — it
  refreshes statuses before it sends.
- **The placeholder AI backend is keyword matching**, not comprehension. It is
  there to prove the workflow, not the analysis quality.
