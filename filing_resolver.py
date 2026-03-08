"""
Filing resolver — picks the best available SEC filing for each company (CIK)
before extraction happens.

Priority order:
  424B4 (3) > S-1/A (2) > S-1 (1)

For S-1/A, the most recent filing by filing_date is preferred when multiple
amendments exist for the same CIK.
"""

from edgar_client import get_424b4_filings, get_s1_filings, get_s1a_filings

# Priority map: higher number wins
PRIORITY: dict[str, int] = {
    "S-1": 1,
    "S-1/A": 2,
    "424B4": 3,
}


def resolve_filings_for_range(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch all S-1, S-1/A, and 424B4 filings in the date range.

    Group by CIK. For each CIK, return only the highest-priority filing.
    When multiple S-1/A amendments exist for the same CIK and no higher-priority
    filing is present, the most recent one (by filing_date) is used.

    Each returned dict includes a ``document_priority`` field set to the
    filing_type of the winning filing.

    Args:
        start_date: YYYY-MM-DD format
        end_date:   YYYY-MM-DD format

    Returns:
        List of resolved filing dicts, one per CIK, each with a
        ``document_priority`` field.
    """
    print(f"  [Resolver] Fetching S-1 filings…")
    s1_filings = get_s1_filings(start_date, end_date)
    print(f"  [Resolver] Found {len(s1_filings)} S-1 filing(s)")

    print(f"  [Resolver] Fetching S-1/A filings…")
    s1a_filings = get_s1a_filings(start_date, end_date)
    print(f"  [Resolver] Found {len(s1a_filings)} S-1/A filing(s)")

    print(f"  [Resolver] Fetching 424B4 filings…")
    b4_filings = get_424b4_filings(start_date, end_date)
    print(f"  [Resolver] Found {len(b4_filings)} 424B4 filing(s)")

    # Group all filings by CIK; track the best candidate per CIK
    # best_by_cik maps cik -> winning filing dict
    best_by_cik: dict[str, dict] = {}

    for filing in s1_filings + s1a_filings + b4_filings:
        cik = filing["cik"]
        incoming_type = filing.get("filing_type", "S-1")
        incoming_priority = PRIORITY.get(incoming_type, 0)

        if cik not in best_by_cik:
            best_by_cik[cik] = {**filing, "document_priority": incoming_type}
            continue

        current = best_by_cik[cik]
        current_type = current.get("document_priority", "S-1")
        current_priority = PRIORITY.get(current_type, 0)

        if incoming_priority > current_priority:
            # Strictly higher-priority type wins outright
            best_by_cik[cik] = {**filing, "document_priority": incoming_type}
        elif incoming_priority == current_priority and incoming_type == "S-1/A":
            # Same type (S-1/A): pick the most recent by filing_date
            if filing.get("filing_date", "") > current.get("filing_date", ""):
                best_by_cik[cik] = {**filing, "document_priority": incoming_type}

    resolved = list(best_by_cik.values())
    print(f"  [Resolver] Resolved to {len(resolved)} unique company filing(s)")
    return resolved


def should_upsert(existing_priority: str, incoming_priority: str) -> bool:
    """
    Return True if the incoming document should replace the existing record.

    An incoming filing replaces an existing one only when its priority is
    strictly higher (424B4 > S-1/A > S-1).

    Args:
        existing_priority: filing_type string of the record already stored
        incoming_priority: filing_type string of the candidate filing

    Returns:
        True if the incoming filing should overwrite the existing record.
    """
    return PRIORITY.get(incoming_priority, 0) > PRIORITY.get(existing_priority, 0)
