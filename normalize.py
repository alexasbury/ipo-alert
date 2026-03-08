"""
Lightweight normalization layer for IPO filing data extracted by Claude.

Converts prose text (lock-up durations, transfer agent addresses, shareholder
lists) into structured, queryable values.
"""

import re
from datetime import date, timedelta
from typing import Optional

from vc_firms import is_vc_firm


# ---------------------------------------------------------------------------
# Lock-up duration
# ---------------------------------------------------------------------------

WORD_TO_NUM = {
    "three": 3,
    "four": 4,
    "six": 6,
    "nine": 9,
    "twelve": 12,
    "eighteen": 18,
}

# Written-out year words that appear in lock-up clauses, e.g. "one year", "two-year lock-up"
WORD_TO_YEARS: dict[str, int] = {
    "one": 1,
    "two": 2,
}

SKIP_PHRASES = {"not found", "not specified", "not available", "pending ipo", "unknown", ""}


def parse_lock_up_days(text: Optional[str]) -> Optional[int]:
    """
    Extract an integer number of lock-up days from English prose.

    Handles:
      - "180 days", "90-day", "180-day lock-up"
      - "6 months", "12 months"
      - "six months", "twelve months", "eighteen months"
      - "three months" / "three-month" → 90
      - "four months" / "four-month" → 120
      - "one year" / "one-year" → 365
      - "two years" / "two-year" → 730

    Returns None if no pattern matches or input is a sentinel.
    """
    if not text or text.strip().lower() in SKIP_PHRASES:
        return None

    t = text.strip()

    # Numeric days: "180 days", "180-day"
    m = re.search(r'(\d+)\s*[-\s]?day', t, re.I)
    if m:
        return int(m.group(1))

    # Numeric months: "6 months", "12 months"
    m = re.search(r'(\d+)\s*month', t, re.I)
    if m:
        return int(m.group(1)) * 30

    # Written-out years: "one year", "two years", "one-year lock-up", "two-year"
    year_pattern = r'\b(' + '|'.join(WORD_TO_YEARS.keys()) + r')[-\s]year'
    m = re.search(year_pattern, t, re.I)
    if m:
        return WORD_TO_YEARS[m.group(1).lower()] * 365

    # Written-out months: "six months", "twelve months", "three-month", etc.
    month_pattern = r'\b(' + '|'.join(WORD_TO_NUM.keys()) + r')[-\s]months?\b'
    m = re.search(month_pattern, t, re.I)
    if m:
        return WORD_TO_NUM[m.group(1).lower()] * 30

    return None


def compute_lock_up_expires_on(
    prospectus_date: Optional[str],
    lock_up_days: Optional[int],
) -> Optional[str]:
    """
    Compute the calendar date when the lock-up expires.

    Args:
        prospectus_date: ISO date string (YYYY-MM-DD)
        lock_up_days:    Integer number of days

    Returns ISO date string, or None if either argument is missing.
    """
    if not prospectus_date or lock_up_days is None:
        return None
    try:
        d = date.fromisoformat(prospectus_date)
        return str(d + timedelta(days=lock_up_days))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Shareholders
# ---------------------------------------------------------------------------

# Pattern 1: "Name (X%)" — parenthesised percentage
_SHAREHOLDER_PAREN_RE = re.compile(r'([^;(]{3,}?)\s*\(\s*(\d+\.?\d*)\s*%')

# Pattern 2: "Name — X%" or "Name - X%" (em/en/hyphen dash then percentage)
_SHAREHOLDER_DASH_RE = re.compile(r'([^;\u2013\u2014\-]{3,}?)\s*[\u2013\u2014\-]\s*(\d+\.?\d*)\s*%')

# Pattern 3: "Name, X%" (comma then percentage)
_SHAREHOLDER_COMMA_RE = re.compile(r'([^;,]{3,}?),\s*(\d+\.?\d*)\s*%')

# Pattern 4: "Name: X%" (colon then percentage)
_SHAREHOLDER_COLON_RE = re.compile(r'([^;:]{3,}?):\s*(\d+\.?\d*)\s*%')


def parse_shareholders(text: Optional[str]) -> Optional[str]:
    """
    Normalize shareholder percentage strings into "Name X%; Name Y%" format.

    Supports four delimiter styles:
      - "Name (X%)"       — parenthesised percentage
      - "Name — X%"       — em dash, en dash, or hyphen-dash
      - "Name, X%"        — comma-separated
      - "Name: X%"        — colon-separated

    Multiple entries should be separated by semicolons in the input.
    Returns None if the input is a sentinel phrase or no shareholders found.
    """
    if not text or text.strip().lower() in SKIP_PHRASES:
        return None

    # Try patterns in priority order: parenthesis first (most specific), then
    # dash, comma, colon.  Use whichever pattern yields the most matches to
    # avoid false positives from partially matching the wrong pattern.
    for pattern in (
        _SHAREHOLDER_PAREN_RE,
        _SHAREHOLDER_DASH_RE,
        _SHAREHOLDER_COMMA_RE,
        _SHAREHOLDER_COLON_RE,
    ):
        matches = pattern.findall(text)
        if matches:
            parts = [f"{name.strip()} {pct}%" for name, pct in matches]
            return "; ".join(parts)

    return None


def validate_vc_backed(
    claude_result: str,
    shareholders_text: Optional[str],
) -> str:
    """
    Cross-check Claude's is_venture_backed result against the known VC firm list.

    If Claude said 'Unknown' or 'No' but a known VC firm appears in
    shareholders_text, override to 'Yes'.  Never downgrade a Claude 'Yes' result.

    Args:
        claude_result:     The raw value returned by Claude: 'Yes', 'No', or 'Unknown'.
        shareholders_text: Free-text shareholder string (may be None).

    Returns:
        'Yes', 'No', or 'Unknown'.
    """
    # Never downgrade a positive signal from Claude.
    if claude_result == "Yes":
        return "Yes"

    # If we have shareholder text, scan it for known VC firm names.
    if shareholders_text:
        if is_vc_firm(shareholders_text):
            return "Yes"

    # Preserve Claude's original assessment.
    if claude_result in ("No", "Unknown"):
        return claude_result

    return "Unknown"


# ---------------------------------------------------------------------------
# Transfer agent
# ---------------------------------------------------------------------------

# Matches a street number that signals the start of a mailing address
_STREET_NUM_RE = re.compile(r',?\s*\d+\s+\w')


def normalize_transfer_agent(text: Optional[str]) -> Optional[str]:
    """
    Strip mailing addresses — keep only the entity name.

    "West Coast Stock Transfer, Inc., 721 N. Vulcan Ave…"
      →  "West Coast Stock Transfer, Inc."

    "Computershare Trust Company, N.A."
      →  "Computershare Trust Company, N.A."  (no change; no street address)

    Returns None if input is a sentinel phrase.
    """
    if not text or text.strip().lower() in SKIP_PHRASES:
        return None

    t = text.strip()

    # Find the first street-number pattern and truncate there
    m = _STREET_NUM_RE.search(t)
    if m:
        t = t[: m.start()].rstrip(", ")

    return t or None


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def normalize_filing(row: dict) -> dict:
    """
    Apply all normalization rules to a filing row dict.

    Returns a dict of derived fields ready to be written back to the DB:
        lock_up_days, lock_up_expires_on, transfer_agent_normalized,
        is_venture_backed_validated
    """
    lock_up_text = row.get("lock_up_expiration_date")
    lock_up_days = parse_lock_up_days(lock_up_text)

    # Only use prospectus_date (424B4 / IPO date) as the lock-up clock base.
    # For pre-IPO S-1 filings without a prospectus_date the expiry cannot yet
    # be computed, so we return None rather than using the S-1 filing_date.
    base_date = row.get("prospectus_date") or None
    lock_up_expires_on = compute_lock_up_expires_on(base_date, lock_up_days)

    transfer_agent_normalized = normalize_transfer_agent(row.get("transfer_agent"))

    claude_vc = row.get("is_venture_backed") or "Unknown"
    shareholders_text = row.get("top_5_percent_shareholders")
    is_venture_backed_validated = validate_vc_backed(claude_vc, shareholders_text)

    return {
        "lock_up_days": lock_up_days,
        "lock_up_expires_on": lock_up_expires_on,
        "transfer_agent_normalized": transfer_agent_normalized,
        "is_venture_backed_validated": is_venture_backed_validated,
    }
