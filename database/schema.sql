-- PFAS Reporting Automation Tool - SQLite schema
-- Applied automatically on first run by app/db.py:init_db().
-- Every statement is idempotent so re-running is harmless.

-- ---------------------------------------------------------------------------
-- sites: one row per manufacturing site that owes an annual PFAS submission.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sites (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,  -- "Site ID"
    site_name            TEXT    NOT NULL UNIQUE,            -- e.g. "Kalamazoo"
    site_lead            TEXT,                               -- responsible person
    site_email           TEXT    NOT NULL,                   -- where reminders go
    region               TEXT,                               -- e.g. "North America"

    -- Workflow state. CHECK keeps bad values out of the DB entirely, so the
    -- dashboard never has to defend against an unexpected status string.
    submission_status    TEXT    NOT NULL DEFAULT 'Pending'
                         CHECK (submission_status IN ('Complete', 'Pending', 'Overdue')),

    last_submission_date TEXT,                               -- ISO date, set when marked Complete
    reminder_count       INTEGER NOT NULL DEFAULT 0,         -- how many reminders sent

    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- The dashboard groups by these two columns constantly.
CREATE INDEX IF NOT EXISTS idx_sites_status ON sites (submission_status);
CREATE INDEX IF NOT EXISTS idx_sites_region ON sites (region);


-- ---------------------------------------------------------------------------
-- reminders: audit log of every reminder the engine generated.
-- Kept separate from `sites` so we retain full history even after a site
-- flips to Complete and its reminder_count stops moving.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER NOT NULL REFERENCES sites (id) ON DELETE CASCADE,
    sent_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    recipient     TEXT    NOT NULL,   -- snapshot of the email at send time
    subject       TEXT    NOT NULL,
    body          TEXT    NOT NULL,

    -- 'sent'    = handed off to the SMTP server successfully
    -- 'dry_run' = generated + logged but deliberately not delivered
    -- 'failed'  = SMTP raised; see error_message
    status        TEXT    NOT NULL DEFAULT 'dry_run'
                  CHECK (status IN ('sent', 'dry_run', 'failed')),
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_reminders_site ON reminders (site_id);


-- ---------------------------------------------------------------------------
-- submissions: the narrative text a site sends in, plus the AI-generated
-- summary of it. One row per analysis run so you can compare over time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS submissions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id            INTEGER REFERENCES sites (id) ON DELETE SET NULL,  -- optional
    submitted_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    raw_text           TEXT    NOT NULL,

    -- Flattened output of generate_summary(). Stored denormalized because
    -- this is a read-mostly record we always render as a whole.
    executive_summary  TEXT,
    key_findings       TEXT,     -- newline-delimited list
    follow_up_required TEXT      -- 'Yes' / 'No'
                       CHECK (follow_up_required IN ('Yes', 'No') OR follow_up_required IS NULL),
    follow_up_reason   TEXT,
    provider           TEXT      -- which backend produced it ('placeholder', 'api', ...)
);

CREATE INDEX IF NOT EXISTS idx_submissions_site ON submissions (site_id);
