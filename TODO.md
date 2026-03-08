# IPO Alert — Agent Work Plan

## Goal

Analyze and extract structured data from S-1 and S-1/A amendment filings published on SEC EDGAR,
store it in a SQLite database daily, and send a weekly summary email covering the previous week's filings.

---

## Automated Pipeline (High-Level)

Scheduling is handled by **GitHub Actions** — no external server or cron daemon needed.

```
Daily GitHub Actions job (runs at 8am UTC, looks back 2 days)
  └─ 1. Fetch S-1, S-1/A, and 424B4 filings filed in the last 2 days from EDGAR
  └─ 2. Per company (CIK), resolve the best available document (424B4 > S-1/A > S-1)
  └─ 3. If company not in DB → insert new record
         If company already in DB and new document has higher priority → update (upsert) record
  └─ 4. Parse the resolved document with Claude to extract structured fields
  └─ 5. Store/update in SQLite (committed back to repo)

Weekly GitHub Actions job (runs every Monday at 9am UTC)
  └─ 6. Send email covering filings from the prior week (Mon–Sun)
         Every filing is included regardless of type, with clear status callout:
         "S-1 (IPO Pending)" | "S-1/A (Amended)" | "424B4 (IPO Confirmed)"
```

**Lookback window:** 2 days (not 1) so that if a daily run is delayed or fails, the following
day's run catches anything missed. The duplicate/upsert logic ensures no filing is double-counted.

**Database persistence:** Since SQLite is a local file, the daily job commits `ipo_filings.db`
back to the repo after each run. This keeps the DB in sync with the codebase and gives a full
audit trail of when each filing was captured. See Subagent 7 for the workflow implementation.

**Future — Backfill Job:** A separate `backfill.py` script (not part of this sprint) will allow
scanning a user-specified historical date range to populate the database with past filings. This
is not part of the automated daily job — it will be run manually on demand.

---

## Background: What Is an S-1 Filing?

An S-1 is a registration statement filed with the SEC by a company preparing to go public (IPO).
Key characteristics agents should understand:

- Filed by the **issuer** (the company going public), not by brokers or investors.
- **S-1** = initial registration. **S-1/A** = amendment (updated draft). Multiple amendments are common.
- **424B4** = the final prospectus filed once an IPO prices. This is the most complete version and often has data not yet in the S-1 (e.g., actual IPO price, confirmed lock-up start date).
- The cover page of an S-1 lists share classes, offering size, and sometimes the expected exchange.
- **Lock-up agreements** restrict insiders and major shareholders from selling shares for a period (typically 90–180 days) after the IPO date.
- **Principal Shareholders** table lists anyone owning 5%+ of any share class pre-offering, with footnotes explaining voting control, related entities, and options included.
- **Transfer Agent** handles shareholder recordkeeping post-IPO. Usually named in "Description of Capital Stock."
- **Legal Counsel** is the issuer's law firm (not the underwriters' counsel). Found on the cover page or "Legal Matters" section.
- **Dual-class structures** (Class A & B) give founders/insiders supervoting rights. Class A is typically the publicly traded share.

Where to find each field in a filing:
- Company Name, CIK, Accession Number → EDGAR metadata (not in the document itself)
- Filing Date → EDGAR metadata
- IPO Date → 424B4 filing date (the date the final prospectus is filed = IPO pricing day)
- Filing Type → EDGAR metadata (`form` field)
- Transfer Agent → "Description of Capital Stock" section or near the end of the document
- Legal Counsel → Cover page or "Legal Matters" section
- Share Classes / Dually Listed → "Description of Capital Stock" or prospectus summary
- Lock-Up Date → Date of final prospectus (424B4 filing date)
- Lock-Up Expiration → "Shares Eligible for Future Sale" or "Underwriting" section
- Lock-Up Terms → Same sections as above
- Top 5%+ Shareholders → "Principal and Selling Stockholders" table
- Venture Backed → Inferred from names in the Principal Shareholders table

---

## Existing Codebase

The project is already partially built. Agents must read and build on existing code — do NOT rewrite from scratch.

| File | Purpose | Status |
|---|---|---|
| `edgar_client.py` | Fetches S-1 and 424B4 filings from EDGAR full-text search API | Complete |
| `filing_parser.py` | Uses Claude (`claude-opus-4-6`) to extract structured fields from HTML | Complete |
| `database.py` | SQLite read/write layer for `ipo_filings` table | Complete |
| `email_sender.py` | Formats and sends weekly HTML email via Gmail SMTP | Complete |
| `normalize.py` | Derives `lock_up_days` and `lock_up_expires_on` from prose text | Complete |
| `main.py` | Orchestrates the daily/weekly pipeline; CLI with `--test`, `--no-email`, `--print-db` flags | Complete |
| `requirements.txt` | Python deps: anthropic, requests, beautifulsoup4, lxml, python-dotenv, pydantic | Complete |
| `queries.sql` | Reference SQL queries for the database | Complete |

### Existing Database Schema (`ipo_filings` table)

```sql
id                                  INTEGER PRIMARY KEY AUTOINCREMENT
company_name                        TEXT NOT NULL
filing_date                         TEXT NOT NULL        -- S-1 filing date (YYYY-MM-DD)
accession_number                    TEXT UNIQUE NOT NULL
cik                                 TEXT NOT NULL
transfer_agent                      TEXT
legal_counsel                       TEXT
dually_listed                       TEXT                 -- e.g. "Class A & Class B"
lock_up_date                        TEXT
lock_up_expiration_date             TEXT                 -- prose (e.g. "180 days after prospectus")
lock_up_terms                       TEXT
top_5_percent_shareholders          TEXT
top_5_percent_shareholders_footnotes TEXT
is_venture_backed                   TEXT                 -- "Yes" / "No" / "Unknown"
prospectus_date                     TEXT                 -- 424B4 filing date ≈ IPO date
document_priority                   TEXT                 -- "424B4", "S-1/A", or "S-1" — which doc was parsed
lock_up_days                        INTEGER              -- derived by normalize.py
lock_up_expires_on                  TEXT                 -- derived by normalize.py (YYYY-MM-DD)
created_at                          TEXT DEFAULT (datetime('now'))
```

---

## Orchestration Agent Instructions

You are the orchestrating agent. Your responsibilities:

1. **Brief subagents** with the S-1 background and field-location guidance above before they begin.
2. **Assign tasks** to subagents as defined below. Subagents 1–4 are independent and can run in parallel. Subagent 5 depends on 1–4. Subagent 6 depends on 5.
3. **Review code** produced by each subagent for correctness, production quality, and consistency with the existing codebase style.
4. **Test and validate** each subagent's code before accepting it. Run `python main.py --test --no-email` to verify the pipeline end-to-end.
5. **Submit a GitHub pull request** once all subagents' code is validated and tests pass.

Coding standards to enforce:
- Python 3.11+, type hints on all function signatures
- Docstrings on all public functions
- No bare `except:` — catch specific exceptions
- Match existing code style (snake_case, single-file modules, no external frameworks beyond what's in `requirements.txt`)
- Secrets via environment variables only (see `.env.example`)

---

## Subagent Tasks

### Subagent 0 — Filing Document Resolution (Prerequisite for Subagents 1–4)

**Goal:** For each company (identified by CIK), determine and retrieve the best available filing
document to parse. Priority order:

```
1. 424B4  (final prospectus — most complete, confirms IPO date and all terms)
2. S-1/A  (most recent amendment — more up-to-date than original S-1)
3. S-1    (original registration statement — fallback)
```

**Gap analysis:**
- `edgar_client.py` `get_s1_filings()` explicitly filters `form_type != "S-1"`, discarding all S-1/A amendments.
- `get_424b4_filings()` fetches 424B4s but only matches them to existing S-1 records by CIK after the fact.
- There is no unified resolution function — the pipeline blindly processes whichever document it first fetches.

**Tasks:**

1. Add `get_s1a_filings(start_date, end_date)` to `edgar_client.py`, following the same pattern as
   `get_s1_filings()` but filtering for `form_type == "S-1/A"`. Return the same dict shape
   (`company_name`, `filing_date`, `accession_number`, `cik`, `filing_type`).

2. Create a `filing_resolver.py` module with a `resolve_filing(cik, start_date, end_date)` function that:
   - Calls `get_424b4_filings()`, `get_s1a_filings()`, and `get_s1_filings()` for the given CIK and date range
   - Applies the priority order above: 424B4 > most recent S-1/A > S-1
   - For S-1/A, selects the **most recent** amendment by `filing_date` if multiple exist
   - Returns a single dict: the winning filing metadata + `filing_type` + `document_priority`
     (`"424B4"`, `"S-1/A"`, or `"S-1"`) so downstream code knows which was used

3. Implement upsert logic in `filing_resolver.py` (or `database.py`) using the following rules:
   - If no record exists for the CIK → insert
   - If a record exists and the incoming document has **equal or lower** priority → skip (no update)
   - If a record exists and the incoming document has **higher** priority (e.g. S-1/A supersedes S-1,
     424B4 supersedes S-1/A) → update the existing record in place, preserving the original `filing_date`
     and `accession_number` from the first S-1, and setting `document_priority` to the new value
   - Priority rank: S-1 = 1, S-1/A = 2, 424B4 = 3

4. Add a `get_filing_document_with_fallback(cik, accession_number)` wrapper in `edgar_client.py`
   that retries with a 1-second backoff up to 3 times before returning `None`, to handle transient
   EDGAR timeouts gracefully.

5. Update `main.py` `process_filings_for_range()` to use `resolve_filing()` instead of calling
   `get_s1_filings()` directly. The lookback window must be **2 days** (not 1). The separate
   `process_prospectuses_for_range()` step becomes unnecessary — the resolver handles 424B4 selection
   — remove it to avoid double-parsing.

6. Add unit tests in `test_filing_resolver.py` that mock the EDGAR API responses and verify:
   - 424B4 is selected when all three types are present
   - Most recent S-1/A is selected when no 424B4 exists and multiple S-1/A amendments are present
   - Original S-1 is selected when only an S-1 exists
   - `None` is returned gracefully when no filings are found for a CIK
   - Upsert: existing S-1 record is updated when an S-1/A arrives for the same CIK
   - Upsert: existing S-1/A record is updated when a 424B4 arrives for the same CIK
   - Upsert: existing 424B4 record is NOT overwritten by a lower-priority document

**Acceptance criteria:**
- `test_filing_resolver.py` passes
- `python main.py --test --no-email` uses the resolved document (verify via print output showing `document_priority`)
- No filing is downloaded or parsed more than once per run
- Lookback window is 2 days

---

### Subagent 1 — Core Filing Info (Depends on Subagent 0)

**Goal:** Ensure `filing_type` and `ipo_date` are properly captured alongside existing fields.

**Gap analysis:**
- `company_name`, `filing_date`, `accession_number`, `cik` are already extracted from EDGAR metadata and stored. No changes needed.
- `filing_type` (S-1 vs S-1/A) is currently **not stored**. `edgar_client.py` already reads `form` from EDGAR but discards it.
- `ipo_date` is approximated by `prospectus_date` (424B4 filing date). This is close but the field should be renamed or documented clearly.

**Tasks:**
1. Modify `edgar_client.py` to include `filing_type` in the returned dict for both `get_s1_filings()` and `get_424b4_filings()`.
2. Add a `filing_type` column to the `ipo_filings` table in `database.py` (use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern already present in `init_db()`).
3. Update `database.py` `save_filing()` and `update_filing_from_prospectus()` to persist `filing_type`.
4. Update `main.py` to pass `filing_type` through the pipeline.
5. Add a code comment in `database.py` clarifying that `prospectus_date` (the 424B4 filing date) is the closest available proxy for `ipo_date`.

**Acceptance criteria:**
- `filing_type` column populated as "S-1" or "S-1/A" for all new filings
- Existing rows not broken by the migration
- `python main.py --test --no-email` runs without errors

---

### Subagent 2 — Key Parties (Depends on Subagent 0)

**Goal:** Validate and improve extraction accuracy for `transfer_agent` and `legal_counsel`.

**Gap analysis:**
- Both fields are already extracted in `filing_parser.py` and stored. Core functionality is complete.
- Extraction quality can be uneven for filings where the section headings differ from expected keywords.

**Tasks:**
1. Review the `_extract_around()` keyword lists in `filing_parser.py` for `transfer_agent` and `legal_counsel` sections.
2. Expand keyword coverage to handle common variants (e.g., "registrar and paying agent", "our counsel", "Latham & Watkins LLP has opined").
3. Add unit tests in a new file `test_parser.py` with at least 3 test cases per field using synthetic HTML snippets.
4. Ensure `normalize_transfer_agent()` in `normalize.py` is called and its result is stored (currently `normalize_filing()` only derives lock-up fields — transfer agent normalization is computed but not written back to DB).

**Acceptance criteria:**
- `test_parser.py` passes (`python -m pytest test_parser.py`)
- Normalized transfer agent name (address stripped) is stored in DB

---

### Subagent 3 — Lock-Up & Share Structure (Depends on Subagent 0)

**Goal:** Validate and improve lock-up and share class extraction and normalization.

**Gap analysis:**
- `dually_listed`, `lock_up_date`, `lock_up_expiration_date`, `lock_up_terms` are extracted.
- `lock_up_days` and `lock_up_expires_on` are derived by `normalize.py` — but only `lock_up_expiration_date` (prose) is used as input; `lock_up_date` is not.
- Lock-up expiry calculation currently falls back to `filing_date` if no `prospectus_date` exists, which can produce incorrect dates for preliminary S-1s.

**Tasks:**
1. Review `normalize.py` `parse_lock_up_days()` — add support for "one year", "two years" word patterns.
2. Update `compute_lock_up_expires_on()` to only use `prospectus_date` as the base date (never `filing_date`), since the lock-up clock starts at IPO, not at S-1 filing.
3. Add unit tests in `test_normalize.py` covering at least: 180-day, 6-month, 1-year, "six months" text, and missing date scenarios.
4. Review the `share_class_signal` detection logic in `filing_parser.py` — confirm "Class C" detection is accurate and not triggered by unrelated "Class C" references.

**Acceptance criteria:**
- `test_normalize.py` passes
- `lock_up_expires_on` is NULL for filings without a `prospectus_date` (not incorrectly computed from `filing_date`)

---

### Subagent 4 — Shareholders (Depends on Subagent 0)

**Goal:** Validate and improve shareholder extraction and venture-backed classification.

**Gap analysis:**
- `top_5_percent_shareholders`, `top_5_percent_shareholders_footnotes`, and `is_venture_backed` are extracted.
- The VC classification relies on Claude's judgment. Known VC firm names should be used as a verification signal.
- Shareholder percentage parsing in `normalize.py` (`parse_shareholders()`) uses a regex that may miss formats like "Name — 12.3%" or "Name, 12%".

**Tasks:**
1. Expand `parse_shareholders()` regex in `normalize.py` to handle dash-separated and comma-percentage formats.
2. Create a reference list `vc_firms.py` with ~50 well-known VC/growth-equity firms (e.g., Sequoia, a16z, Kleiner Perkins, Tiger Global, General Atlantic) to use as a secondary validation signal for `is_venture_backed`.
3. Add a `validate_vc_backed()` function that cross-checks Claude's `is_venture_backed` result against the shareholders text and the reference list — override to "Yes" if a known VC name is found.
4. Add unit tests in `test_shareholders.py` for the parser and VC validator.

**Acceptance criteria:**
- `test_shareholders.py` passes
- `is_venture_backed` is never "Unknown" when a VC firm from the reference list appears in the shareholders text

---

### Subagent 5 — Database (Depends on Subagents 1–4)

**Goal:** Integrate all new fields and ensure the database layer is complete and robust.

**Tasks:**
1. After Subagents 1–4 complete, audit `database.py` to confirm all new fields (from Subagents 1–4) are included in `save_filing()`, `update_filing_from_prospectus()`, and `get_all_filings()`.
2. Add a `get_filings_for_email(week_start: str, week_end: str)` function that queries by `filing_date` range and returns all fields needed for the email template.
3. Add a database integrity check: a function `audit_db()` that prints counts of NULL values per column — useful for diagnosing extraction gaps.
4. Write a migration script `migrate_db.py` that safely applies all new `ALTER TABLE` changes to an existing `ipo_filings.db` without data loss.
5. Add unit tests in `test_database.py` using an in-memory SQLite DB (`:memory:`).

**Acceptance criteria:**
- `test_database.py` passes
- `migrate_db.py` runs cleanly against the existing `ipo_filings.db`
- `python main.py --print-db` outputs all fields including new ones

---

### Subagent 6 — Weekly Email (Depends on Subagent 5)

**Goal:** Ensure the email is complete, accurate, and includes all extracted fields.

**Gap analysis:**
- `email_sender.py` is functional but the HTML template does not include `filing_type`, `lock_up_days`, or `lock_up_expires_on`.
- The email only covers S-1 filings; it should note which have been enriched with 424B4 data (confirmed IPO) vs. still pending.

**Filing status labels (use consistently across email and DB):**
- `"S-1 — IPO Pending"` → only an original S-1 has been filed; no IPO date confirmed yet
- `"S-1/A — Amended"` → an amendment has been filed; IPO date still not confirmed
- `"424B4 — IPO Confirmed"` → final prospectus filed; IPO date and all terms are known

**Tasks:**
1. Update `format_html_email()` and `format_plain_email()` in `email_sender.py` to include:
   - A prominent status badge per filing using the labels above (derived from `document_priority`)
   - `lock_up_days` and `lock_up_expires_on` (computed lock-up expiry date)
   - All filings from the prior week are included — no filtering by status
2. Add a second section to the email for **upcoming lock-up expirations** (next 30 days) — pull from `get_upcoming_lockups()` in `database.py`.
3. Ensure the email renders correctly in major email clients (use inline CSS, no external stylesheets).
4. Add a `--preview-email` CLI flag to `main.py` that writes `email_preview.html` without sending.

**Recipients:** `alexanderasbury@gmail.com`, `trishajeffries@gmail.com` — confirm these are set in `.env` and `.env.example` as a comma-separated `RECIPIENT_EMAIL` value.

**Acceptance criteria:**
- `python main.py --test --no-email` produces a complete `email_preview.html`
- All extracted fields visible in the preview
- Upcoming lock-up section renders correctly

---

### Subagent 7 — GitHub Actions Workflows (Depends on Subagent 5)

**Goal:** Automate the daily extraction and weekly email via GitHub Actions. No external scheduler needed.

**Context:**
- Secrets (`ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`, `GMAIL_USER`, `RECIPIENT_EMAIL`) must be added to
  the repo under Settings → Secrets → Actions. They are never stored in code or committed.
- `ipo_filings.db` is committed back to the repo after each daily run to persist data between jobs.
  The commit is made by the workflow using the `GITHUB_TOKEN` (no extra credentials needed).
- GitHub Actions cron runs on UTC. Free-tier jobs can occasionally be delayed 15–30 min during peak load.

**Tasks:**

1. Create `.github/workflows/daily_extract.yml`:
   - Trigger: `schedule` cron `'0 8 * * *'` (daily at 8am UTC) + `workflow_dispatch` (manual trigger)
   - Runner: `ubuntu-latest`
   - Steps:
     1. Checkout repo (with `persist-credentials: true` so the commit step works)
     2. Set up Python 3.11
     3. Install dependencies from `requirements.txt`
     4. Run `python main.py --no-email` (extract and store only)
     5. Commit and push `ipo_filings.db` back to the repo if it changed
        (use `git diff --quiet` to skip the commit if no new filings were found)
   - Inject secrets: `ANTHROPIC_API_KEY`

2. Create `.github/workflows/weekly_email.yml`:
   - Trigger: `schedule` cron `'0 9 * * 1'` (every Monday at 9am UTC) + `workflow_dispatch`
   - Runner: `ubuntu-latest`
   - Steps:
     1. Checkout repo
     2. Set up Python 3.11
     3. Install dependencies
     4. Run `python main.py` (production mode: reads last week's filings from DB, sends email)
   - Inject secrets: `ANTHROPIC_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`

3. Add a `.github/workflows/test.yml` CI workflow:
   - Trigger: `push` and `pull_request` on `main`
   - Steps: install deps, run `python -m pytest` across all test files
   - Does NOT inject live API secrets — tests must use mocks/fixtures for Claude and SMTP calls

4. Update `.gitignore` to ensure `.env` remains ignored but `ipo_filings.db` is explicitly tracked:
   ```
   .env
   # ipo_filings.db is intentionally tracked for persistence between CI runs
   ```

5. Add a `README.md` section (or update if it exists) documenting:
   - How to add the required GitHub Actions secrets
   - How to trigger a manual run via `workflow_dispatch`
   - How to run locally with `.env`

**Acceptance criteria:**
- All three workflow YAML files are valid (use `actionlint` or push to a test branch to verify)
- `workflow_dispatch` manual trigger works for both daily and weekly jobs
- Daily job only commits DB when new filings were actually added
- CI test workflow passes on every PR without requiring live API keys

---

### Future — Backfill Job (Not Part of This Sprint)

A standalone `backfill.py` script to be built separately, allowing on-demand historical data collection.

**Planned behavior:**
- Accept `--start` and `--end` date arguments (e.g. `python backfill.py --start 2024-01-01 --end 2024-12-31`)
- Iterates through each week in the range, calling the same resolver and extraction pipeline
- Respects EDGAR rate limits (throttle between requests)
- Uses the same upsert logic — safe to re-run over already-populated date ranges
- Can be triggered manually via GitHub Actions `workflow_dispatch` with date inputs

This is out of scope for the current sprint but the upsert logic from Subagent 0 makes it straightforward to implement later.

---

## Testing & Validation (Orchestrator)

Once all subagents complete, run the full validation suite:

```bash
# Unit tests
python -m pytest test_parser.py test_normalize.py test_shareholders.py test_database.py -v

# End-to-end pipeline test (fetches real EDGAR data, no email sent)
python main.py --test --no-email

# Inspect the database
python main.py --print-db

# Check lock-up expirations
python main.py --upcoming-lockups

# Preview email
python main.py --test --no-email   # check email_preview.html
```

---

## Pull Request Checklist

- [ ] All unit tests pass (`test_filing_resolver.py`, `test_parser.py`, `test_normalize.py`, `test_shareholders.py`, `test_database.py`)
- [ ] `python main.py --test --no-email` runs end-to-end without errors
- [ ] `migrate_db.py` runs cleanly against existing DB
- [ ] `email_preview.html` renders all fields
- [ ] No secrets or `.env` files committed
- [ ] `.github/workflows/daily_extract.yml` is valid YAML and triggers correctly
- [ ] `.github/workflows/weekly_email.yml` is valid YAML and triggers correctly
- [ ] `.github/workflows/test.yml` CI passes on the PR branch
- [ ] GitHub Actions secrets documented in README
- [ ] PR description summarizes what each subagent added
