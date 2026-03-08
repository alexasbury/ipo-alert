"""
Daily IPO Alert — main entry point.

Usage:
    python main.py             # production: process last 2 days + send email
    python main.py --test      # test: process 3 recent filings + send email
    python main.py --test --no-email   # test without sending (writes email_preview.html)
    python main.py --preview-email     # write email_preview.html from DB, no send
    python main.py --print-db  # dump all stored filings to stdout
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from database import (
    apply_normalization,
    audit_db,
    get_all_filings,
    get_filing_by_accession,
    get_filings_for_email,
    get_upcoming_lockups,
    init_db,
    upsert_filing,
)
from normalize import normalize_filing
from edgar_client import get_filing_document_with_fallback
from email_sender import format_html_email, send_email
from filing_parser import parse_filing
from filing_resolver import resolve_filings_for_range

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


def _last_two_days() -> tuple[str, str]:
    """Return (start, end) covering the last 2 days up to today (inclusive)."""
    today = datetime.now().date()
    start = today - timedelta(days=2)
    return str(start), str(today)


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
    Resolve the best available filing per company in [start, end], then
    download, parse, and upsert each one.

    Uses the resolver to pick the highest-priority filing type per CIK
    (424B4 > S-1/A > S-1), downloads documents with retry fallback, and
    uses upsert logic so a higher-priority filing will replace a lower one.

    Args:
        start: YYYY-MM-DD start of date range
        end:   YYYY-MM-DD end of date range
        limit: Optional cap on the number of filings to process

    Returns:
        List of filing dicts that were inserted or updated (plus previously
        cached rows where the accession number is already stored).
    """
    print(f"\n[Resolver] Resolving best filings: {start} → {end}")
    filing_metas = resolve_filings_for_range(start, end)
    print(f"[Resolver] {len(filing_metas)} company filing(s) after resolution")

    if limit:
        filing_metas = filing_metas[:limit]

    results: list[dict] = []

    for i, meta in enumerate(filing_metas):
        company = meta["company_name"]
        acc = meta["accession_number"]
        cik = meta["cik"]
        doc_priority = meta.get("document_priority", meta.get("filing_type", "S-1"))
        print(f"\n  [{i + 1}/{len(filing_metas)}] {company}  ({acc})")
        print(f"  [Resolver] {company} → {doc_priority}")

        # Check if this exact accession is already stored (already processed)
        cached = get_filing_by_accession(acc)
        if cached:
            print("    Already in database — loading cached data.")
            results.append(cached)
            continue

        print("    Downloading filing document…")
        html = get_filing_document_with_fallback(cik, acc)
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

        filing_dict = {**filing.to_dict(), "document_priority": doc_priority, "filing_type": doc_priority}
        outcome = upsert_filing(filing_dict)
        print(f"    Upsert result: {outcome}.")

        if outcome in ("inserted", "updated"):
            apply_normalization(acc, normalize_filing(filing_dict))
            results.append(filing_dict)
        elif outcome == "skipped":
            # A higher-priority record is already stored; return the existing row
            existing = get_filing_by_accession(acc)
            if existing:
                results.append(existing)

    return results


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_test_mode(send: bool = True) -> None:
    """
    Gather up to TEST_TARGET recent S-1 filings (expanding date window if
    needed) and send a test email.

    When send=False, writes an HTML preview to email_preview.html instead.

    Args:
        send: If True, send the email; if False, write a local HTML preview.
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

    upcoming_lockups = get_upcoming_lockups(days_ahead=30)

    _print_summary(collected)

    if send:
        send_email(collected, week_start, week_end, upcoming_lockups=upcoming_lockups, test_mode=True)
    else:
        print("\n[Email] --no-email flag set, skipping send.")
        html = format_html_email(collected, week_start, week_end, upcoming_lockups=upcoming_lockups)
        preview_path = os.path.abspath("email_preview.html")
        with open(preview_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[Email] Preview written to {preview_path}")


def run_weekly_job() -> None:
    """
    Production job: process the last 2 days of filings and send the email.

    The 2-day lookback acts as a safety buffer to catch any filings that
    arrived late or were missed in the previous run.

    Fetches upcoming lock-up expirations from the database and includes
    them in the email.
    """
    init_db()
    run_start, run_end = _last_two_days()
    print(f"[Main] Daily run for {run_start} → {run_end}")

    filings = process_filings_for_range(run_start, run_end)
    print(f"\n[Main] {len(filings)} filing(s) to include in email.")

    # Use get_filings_for_email to pull the full, normalized DB records for
    # the current date range (includes all columns written by apply_normalization).
    email_filings = get_filings_for_email(run_start, run_end)
    upcoming_lockups = get_upcoming_lockups(days_ahead=30)

    send_email(email_filings, run_start, run_end, upcoming_lockups=upcoming_lockups, test_mode=False)


def run_preview_email() -> None:
    """
    Write email_preview.html from the last week's DB filings without sending.

    Fetches:
    - Last week's filings via get_filings_for_email()
    - Upcoming lock-up expirations via get_upcoming_lockups(days_ahead=30)

    Writes the rendered HTML to email_preview.html and prints the absolute path.
    """
    init_db()
    week_start, week_end = _previous_week()
    print(f"[Preview] Fetching filings for {week_start} → {week_end}")

    filings = get_filings_for_email(week_start, week_end)
    upcoming_lockups = get_upcoming_lockups(days_ahead=30)

    print(f"[Preview] {len(filings)} filing(s) found, {len(upcoming_lockups)} upcoming lock-up(s).")

    html = format_html_email(filings, week_start, week_end, upcoming_lockups=upcoming_lockups)
    preview_path = os.path.abspath("email_preview.html")
    with open(preview_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[Preview] Written to {preview_path}")


def run_print_db() -> None:
    """Dump all stored filings as formatted JSON."""
    init_db()
    rows = get_all_filings()
    print(json.dumps(rows, indent=2, default=str))


def run_normalize() -> None:
    """Backfill lock_up_days / lock_up_expires_on for all rows where it is NULL."""
    init_db()
    rows = get_all_filings()
    updated = 0
    for row in rows:
        if row.get("lock_up_days") is None:
            derived = normalize_filing(row)
            if derived.get("lock_up_days") is not None or derived.get("lock_up_expires_on") is not None:
                apply_normalization(row["accession_number"], derived)
                updated += 1
                print(
                    f"  {row['company_name']:40s}  "
                    f"days={derived['lock_up_days']}  expires={derived['lock_up_expires_on']}"
                )
    print(f"\n[Normalize] Updated {updated} of {len(rows)} row(s).")


def run_upcoming_lockups(days_ahead: int = 30) -> None:
    """Print filings whose lock-up expires within the next `days_ahead` days."""
    init_db()
    rows = get_upcoming_lockups(days_ahead=days_ahead)
    if not rows:
        print(f"No lock-ups expiring in the next {days_ahead} days.")
        return
    print(f"\nUpcoming lock-up expirations (next {days_ahead} days):\n")
    for r in rows:
        print(f"  {r['company_name']:40s}  expires {r['lock_up_expires_on']}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_summary(filings: list[dict]) -> None:
    """Print a human-readable summary of processed filings to stdout."""
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY — {len(filings)} filing(s)")
    print(f"{'=' * 60}")
    for f in filings:
        print(f"\n  Company:         {f.get('company_name')}")
        print(f"  Filed:           {f.get('filing_date')}")
        print(f"  Doc Priority:    {f.get('document_priority', f.get('filing_type', 'N/A'))}")
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
    """Parse CLI arguments and dispatch to the appropriate run mode."""
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
        "--preview-email",
        action="store_true",
        help=(
            "Fetch last week's filings from DB, render email_preview.html, and exit "
            "without sending. Prints the output path on completion."
        ),
    )
    parser.add_argument(
        "--print-db",
        action="store_true",
        help="Print all stored filings as JSON and exit",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Backfill lock_up_days and lock_up_expires_on for all rows and exit",
    )
    parser.add_argument(
        "--upcoming-lockups",
        action="store_true",
        help="Print filings with lock-ups expiring in the next 30 days and exit",
    )
    parser.add_argument(
        "--audit-db",
        action="store_true",
        help="Print NULL counts per column for all stored filings and exit",
    )
    args = parser.parse_args()

    if args.print_db:
        run_print_db()
    elif args.normalize:
        run_normalize()
    elif args.upcoming_lockups:
        run_upcoming_lockups()
    elif args.audit_db:
        init_db()
        audit_db()
    elif args.preview_email:
        run_preview_email()
    elif args.test:
        run_test_mode(send=not args.no_email)
    else:
        run_weekly_job()


if __name__ == "__main__":
    main()
