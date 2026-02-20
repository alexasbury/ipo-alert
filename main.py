"""
Weekly IPO S-1 Alert — main entry point.

Usage:
    python main.py             # production: process previous week + send email
    python main.py --test      # test: process 3 recent filings + send email
    python main.py --test --no-email   # test without sending
    python main.py --print-db  # dump all stored filings to stdout
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from database import filing_exists, get_all_filings, get_filing_by_accession, init_db, save_filing
from edgar_client import get_filing_document, get_s1_filings
from email_sender import format_html_email, send_email
from filing_parser import parse_filing

# Maximum filings to retrieve in test mode; look back this many weeks
TEST_TARGET = 3
TEST_MAX_WEEKS_BACK = 6


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _previous_week() -> tuple[str, str]:
    """Return (monday, sunday) of the calendar week prior to today."""
    today = datetime.now().date()
    # Monday of the current week
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)
    last_sunday = last_monday + timedelta(days=6)
    return str(last_monday), str(last_sunday)


def _week_range(weeks_ago: int) -> tuple[str, str]:
    """Return (monday, sunday) for `weeks_ago` weeks before this week."""
    today = datetime.now().date()
    this_monday = today - timedelta(days=today.weekday())
    target_monday = this_monday - timedelta(weeks=weeks_ago)
    target_sunday = target_monday + timedelta(days=6)
    return str(target_monday), str(target_sunday)


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_filings_for_range(
    start: str, end: str, limit: int | None = None
) -> list[dict]:
    """
    Fetch, parse, and store S-1 filings in [start, end].
    Skips filings already in the database.
    Returns list of dicts (new + cached from DB).
    """
    print(f"\n[EDGAR] Searching for S-1 filings: {start} → {end}")
    filing_metas = get_s1_filings(start, end)
    print(f"[EDGAR] Found {len(filing_metas)} filing(s)")

    if limit:
        filing_metas = filing_metas[:limit]

    results: list[dict] = []

    for i, meta in enumerate(filing_metas):
        company = meta["company_name"]
        acc = meta["accession_number"]
        cik = meta["cik"]
        print(f"\n  [{i + 1}/{len(filing_metas)}] {company}  ({acc})")

        # Return cached row if already processed
        if filing_exists(acc):
            print("    Already in database — loading cached data.")
            row = get_filing_by_accession(acc)
            if row:
                results.append(row)
            continue

        print("    Downloading filing document…")
        html = get_filing_document(cik, acc)
        if not html:
            print("    Could not download document — skipping.")
            continue

        print("    Parsing with Claude (this may take 15–45 seconds)…")
        filing = parse_filing(
            company_name=company,
            filing_date=meta["filing_date"],
            accession_number=acc,
            cik=cik,
            html_content=html,
        )

        save_filing(filing)
        print("    Saved to database.")
        results.append(filing.to_dict())

    return results


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_test_mode(send: bool = True) -> None:
    """
    Gather up to TEST_TARGET recent S-1 filings (expanding date window if
    needed) and send a test email.
    """
    print("=" * 60)
    print("  TEST MODE")
    print("=" * 60)
    init_db()

    collected: list[dict] = []
    week = 1

    while len(collected) < TEST_TARGET and week <= TEST_MAX_WEEKS_BACK:
        needed = TEST_TARGET - len(collected)
        start, end = _week_range(week)
        batch = process_filings_for_range(start, end, limit=needed)
        collected.extend(batch)
        week += 1

    if not collected:
        print("\n[Main] No filings found — check EDGAR connectivity.")
        return

    # Determine date range for email subject
    dates = [f.get("filing_date", "") for f in collected if f.get("filing_date")]
    week_start = min(dates) if dates else "N/A"
    week_end = max(dates) if dates else "N/A"

    _print_summary(collected)

    if send:
        send_email(collected, week_start, week_end, test_mode=True)
    else:
        print("\n[Email] --no-email flag set, skipping send.")
        html = format_html_email(collected, week_start, week_end)
        preview_path = "email_preview.html"
        with open(preview_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[Email] Preview written to {preview_path}")


def run_weekly_job() -> None:
    """
    Production job: process last week's S-1 filings and send the email.
    """
    init_db()
    week_start, week_end = _previous_week()
    print(f"[Main] Weekly run for {week_start} → {week_end}")

    filings = process_filings_for_range(week_start, week_end)
    print(f"\n[Main] {len(filings)} filing(s) to include in email.")

    send_email(filings, week_start, week_end, test_mode=False)


def run_print_db() -> None:
    """Dump all stored filings as formatted JSON."""
    init_db()
    rows = get_all_filings()
    print(json.dumps(rows, indent=2, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_summary(filings: list[dict]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY — {len(filings)} filing(s)")
    print(f"{'=' * 60}")
    for f in filings:
        print(f"\n  Company:         {f.get('company_name')}")
        print(f"  Filed:           {f.get('filing_date')}")
        print(f"  Transfer Agent:  {f.get('transfer_agent')}")
        print(f"  Legal Counsel:   {f.get('legal_counsel')}")
        print(f"  Share Classes:   {f.get('dually_listed')}")
        print(f"  Lock-Up Terms:   {f.get('lock_up_terms')}")
        print(f"  Top 5% Holders:  {f.get('top_5_percent_shareholders')}")
        print(f"  VC Backed:       {f.get('is_venture_backed')}")
        print(f"  {'─' * 50}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly IPO S-1 Alert")
    parser.add_argument(
        "--test",
        action="store_true",
        help=f"Test mode: process {TEST_TARGET} recent S-1 filings",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending email (saves HTML preview to email_preview.html instead)",
    )
    parser.add_argument(
        "--print-db",
        action="store_true",
        help="Print all stored filings as JSON and exit",
    )
    args = parser.parse_args()

    if args.print_db:
        run_print_db()
    elif args.test:
        run_test_mode(send=not args.no_email)
    else:
        run_weekly_job()


if __name__ == "__main__":
    main()
