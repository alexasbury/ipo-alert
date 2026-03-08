# IPO Alert

Automatically tracks SEC EDGAR S-1 and S-1/A IPO filings, extracts structured data using Claude AI, and sends a weekly email digest.

## How It Works

1. **Daily (8am UTC):** GitHub Actions fetches new S-1/S-1/A/424B4 filings, parses them with Claude, and stores results in `ipo_filings.db`.
2. **Weekly (Monday 9am UTC):** Sends an email digest covering the prior week's filings to configured recipients.

## Setup

### Required GitHub Actions Secrets

Add these in your repo under **Settings -> Secrets -> Actions**:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GMAIL_USER` | Gmail address used to send emails |
| `GMAIL_APP_PASSWORD` | Gmail app password (not your regular password) |
| `RECIPIENT_EMAIL` | Comma-separated list of recipient emails |

### Running Locally

1. Copy `.env.example` to `.env` and fill in your values
2. Install deps: `pip install -r requirements.txt`
3. Test run (no email): `python main.py --test --no-email`
4. Preview email: `python main.py --preview-email`
5. Full test suite: `python -m pytest -v`

### Manual Trigger

Go to **Actions -> Daily S-1 Extract -> Run workflow** (or Weekly IPO Email) to trigger manually via `workflow_dispatch`.

### Database

`ipo_filings.db` is a SQLite database committed to the repo. Run `python main.py --audit-db` to inspect NULL counts per column. Run `python migrate_db.py` to apply schema migrations to an existing database.
