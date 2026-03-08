# IPO Alert

Automatically tracks SEC EDGAR S-1, S-1/A, and 424B4 IPO filings, extracts structured data using Claude AI, and sends a weekly email digest.

## What It Does

Every day, a GitHub Actions job fetches new IPO filings from the SEC and parses each one with Claude to extract:

- **Company info** — name, CIK, filing date, filing type
- **IPO status** — S-1 (pending), S-1/A (amended), or 424B4 (confirmed IPO date)
- **Key parties** — transfer agent, legal counsel
- **Share structure** — single class, dual class (A & B), or triple class
- **Lock-up details** — start date, expiration date, duration in days, full terms
- **Shareholders** — all entities owning 5%+ of any share class, with footnotes
- **VC-backed** — Yes / No, cross-checked against a reference list of 63 known VC firms

Every Monday, a second job sends an email covering the previous week's filings. The email includes all extracted fields, filing status badges, and a table of upcoming lock-up expirations in the next 30 days.

## Filing Priority

For each company (identified by CIK), the pipeline always uses the most authoritative available document:

```
424B4 (IPO Confirmed)  >  S-1/A (Amended)  >  S-1 (IPO Pending)
```

If a company's S-1 is stored and a 424B4 later arrives, the record is updated in-place with the richer data. No duplicate rows are created per company.

## Architecture

```
SEC EDGAR API
     │
     ▼
filing_resolver.py   ← picks best document per company (CIK)
     │
     ▼
edgar_client.py      ← downloads HTML from EDGAR archives
     │
     ▼
filing_parser.py     ← Claude (claude-opus-4-6) extracts structured fields
     │
     ▼
normalize.py         ← derives lock_up_days, lock_up_expires_on, validates VC flag
     │
     ▼
database.py          ← upserts into ipo_filings.db (SQLite)
     │
     ▼
email_sender.py      ← formats and sends HTML + plain-text email via Gmail SMTP
```

## Automated Schedule (GitHub Actions)

| Workflow | Schedule | Command | Purpose |
|---|---|---|---|
| `daily_extract.yml` | Daily 8am UTC | `python main.py --no-email` | Fetch last 2 days, store in DB |
| `weekly_email.yml` | Monday 9am UTC | `python main.py` | Catch-up fetch + send prior-week email |
| `test.yml` | Every push / PR | `pytest` | Run full test suite (no live API keys) |

The daily job commits `ipo_filings.db` back to the repo after each run. If a run is delayed or fails, the 2-day lookback window ensures the next run recovers any missed filings.

## Setup

### 1. Clone the repo and install dependencies

```bash
git clone https://github.com/alexasbury/ipo-alert.git
cd ipo-alert
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (used by Claude to parse filings) |
| `GMAIL_USER` | Gmail address used to send the weekly email |
| `GMAIL_APP_PASSWORD` | Gmail App Password — **not** your regular password. Generate one at myaccount.google.com → Security → App passwords |
| `RECIPIENT_EMAIL` | Comma-separated list of recipient emails (e.g. `alice@example.com,bob@example.com`) |

### 3. Add GitHub Actions secrets

For the automated workflows to run, add the same four variables as secrets in your repo:

**Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GMAIL_USER` | Sending Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password |
| `RECIPIENT_EMAIL` | Comma-separated recipient list |

### 4. Initialize the database

```bash
python migrate_db.py
```

This creates `ipo_filings.db` with the full schema if it doesn't exist, or safely adds any new columns to an existing database.

## Running Locally

```bash
# Extract last 2 days of filings, store in DB, no email
python main.py --no-email

# Send the previous week's email immediately
python main.py

# Test run: process 3 recent filings, write email_preview.html (no send)
python main.py --test --no-email

# Preview last week's email from the database (no send)
python main.py --preview-email

# Inspect the database
python main.py --print-db     # dump all rows as JSON
python main.py --audit-db     # NULL counts per column

# Inspect upcoming lock-up expirations
python main.py --upcoming-lockups

# Run the full test suite
python -m pytest -v
```

## Manual Trigger

To run either workflow on demand without waiting for the schedule:

1. Go to **Actions** in your GitHub repo
2. Select **Daily S-1 Extract** or **Weekly IPO Email**
3. Click **Run workflow**

## Database Schema

`ipo_filings.db` is a SQLite file committed to the repo. Each row represents one company.

| Column | Type | Description |
|---|---|---|
| `company_name` | TEXT | Company name from EDGAR metadata |
| `filing_date` | TEXT | Date of the original S-1 filing (YYYY-MM-DD) |
| `accession_number` | TEXT | EDGAR accession number of the original S-1 |
| `cik` | TEXT | SEC Central Index Key — unique per company |
| `filing_type` | TEXT | Document type stored: S-1, S-1/A, or 424B4 |
| `document_priority` | TEXT | Same as filing_type — tracks which doc was parsed |
| `transfer_agent` | TEXT | Raw transfer agent name from filing |
| `transfer_agent_normalized` | TEXT | Transfer agent name with mailing address stripped |
| `legal_counsel` | TEXT | Issuer's law firm |
| `dually_listed` | TEXT | Share class structure (e.g. "Class A & Class B") |
| `lock_up_date` | TEXT | Lock-up start date (usually IPO date) |
| `lock_up_expiration_date` | TEXT | Raw lock-up expiry prose from filing |
| `lock_up_terms` | TEXT | Summary of lock-up restrictions |
| `lock_up_days` | INTEGER | Parsed lock-up duration in days |
| `lock_up_expires_on` | TEXT | Computed expiry date (YYYY-MM-DD) |
| `top_5_percent_shareholders` | TEXT | Entities owning 5%+ of any share class |
| `top_5_percent_shareholders_footnotes` | TEXT | Footnotes from the principal shareholders table |
| `is_venture_backed` | TEXT | Yes / No / Unknown (Claude's assessment) |
| `is_venture_backed_validated` | TEXT | Yes / No / Unknown (cross-checked against VC firm list) |
| `prospectus_date` | TEXT | 424B4 filing date — closest proxy for the IPO date |
| `created_at` | TEXT | Row creation timestamp |

Run useful queries directly:

```bash
sqlite3 ipo_filings.db < queries.sql
```

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point and CLI |
| `filing_resolver.py` | Picks best filing per company (priority logic) |
| `edgar_client.py` | Fetches filings and documents from SEC EDGAR |
| `filing_parser.py` | Claude-powered field extraction from HTML |
| `normalize.py` | Derives computed fields; validates VC classification |
| `vc_firms.py` | Reference list of 63 known VC / growth equity firms |
| `database.py` | SQLite read/write layer |
| `email_sender.py` | HTML + plain-text email formatting and sending |
| `migrate_db.py` | Safe schema migration script |
| `queries.sql` | Reference SQL queries for the database |

## Data Disclaimer

Data is sourced from SEC EDGAR public filings and extracted by Claude AI. Always verify extracted information against the original filing before making any investment or business decisions. Extracted fields — especially preliminary S-1 data — may be incomplete or subject to change.
