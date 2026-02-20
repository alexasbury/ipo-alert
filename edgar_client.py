"""
SEC EDGAR API client for fetching S-1 filings.
"""

import time
import requests
from typing import Optional

# EDGAR requires a User-Agent header with contact info
HEADERS = {
    "User-Agent": "IPO Alert alexanderasbury@gmail.com",
    "Accept": "application/json",
}

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"


def get_s1_filings(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch original S-1 filings from EDGAR for a given date range.

    Args:
        start_date: YYYY-MM-DD format
        end_date:   YYYY-MM-DD format

    Returns:
        List of dicts with keys: company_name, filing_date, accession_number, cik
    """
    params = {
        "q": '""',
        "forms": "S-1",
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "hits.hits.total.value": "true",
        "from": 0,
    }

    filings = []
    batch_size = 40

    while True:
        try:
            response = requests.get(
                EDGAR_SEARCH_URL, params=params, headers=HEADERS, timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"  [EDGAR] Error fetching filings: {e}")
            break

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            form_type = source.get("form_type", "")

            # Only original S-1s, not amendments (S-1/A)
            if form_type != "S-1":
                continue

            ciks = source.get("ciks", [])
            raw_cik = ciks[0] if ciks else ""
            # Strip leading zeros for URL usage
            cik = str(int(raw_cik)) if raw_cik.isdigit() else raw_cik

            filings.append({
                "company_name": source.get("entity_name", "Unknown"),
                "filing_date": source.get("file_date", ""),
                "accession_number": hit.get("_id", ""),
                "cik": cik,
            })

        from_val = params["from"] + len(hits)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        if from_val >= total:
            break

        params["from"] = from_val
        time.sleep(0.4)  # Be respectful of EDGAR rate limits

    return filings


def get_filing_document(cik: str, accession_number: str) -> Optional[str]:
    """
    Download the primary HTML document for an S-1 filing.

    Args:
        cik:              Company CIK (without leading zeros)
        accession_number: Format like "0001234567-26-000123"

    Returns:
        HTML content as string, or None on failure
    """
    accession_no_dashes = accession_number.replace("-", "")

    # Fetch the filing index JSON
    index_url = (
        f"{EDGAR_ARCHIVES_URL}/{cik}/{accession_no_dashes}"
        f"/{accession_number}-index.json"
    )

    try:
        time.sleep(0.3)
        resp = requests.get(index_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        index_data = resp.json()
    except Exception as e:
        print(f"  [EDGAR] Could not fetch filing index for {accession_number}: {e}")
        return None

    # Find the primary S-1 HTML document
    files = index_data.get("directory", {}).get("item", [])
    doc_url = _find_primary_document(cik, accession_no_dashes, files)

    if not doc_url:
        print(f"  [EDGAR] No HTML document found for {accession_number}")
        return None

    try:
        time.sleep(0.3)
        resp = requests.get(doc_url, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [EDGAR] Error downloading filing document: {e}")
        return None


def _find_primary_document(
    cik: str, accession_no_dashes: str, files: list[dict]
) -> Optional[str]:
    """
    Pick the best HTML document from a filing's file list.
    Preference order: typed S-1 .htm > any .htm > any .html
    """
    base = f"{EDGAR_ARCHIVES_URL}/{cik}/{accession_no_dashes}"

    # Prefer file explicitly typed as S-1
    for f in files:
        if f.get("type") == "S-1":
            name = f.get("name", "")
            if name.lower().endswith((".htm", ".html")):
                return f"{base}/{name}"

    # Fallback: first .htm file
    for f in files:
        name = f.get("name", "")
        if name.lower().endswith(".htm"):
            return f"{base}/{name}"

    # Fallback: first .html file
    for f in files:
        name = f.get("name", "")
        if name.lower().endswith(".html"):
            return f"{base}/{name}"

    return None
