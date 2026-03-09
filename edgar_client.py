"""
SEC EDGAR API client for fetching S-1, S-1/A, and 424B4 filings.
"""

import os
import time
import requests
from typing import Optional

# EDGAR requires a User-Agent header with a valid contact email.
# Set EDGAR_CONTACT_EMAIL in your environment / .env file.
# Validation is deferred to first use so that importing this module in tests
# (where HTTP calls are mocked) does not require the variable to be set.
def _get_headers() -> dict:
    contact_email = os.environ.get("EDGAR_CONTACT_EMAIL", "")
    if not contact_email:
        raise EnvironmentError(
            "EDGAR_CONTACT_EMAIL is not set. "
            "SEC EDGAR requires a valid contact email in the User-Agent header. "
            "Add it to your .env file or GitHub Actions secrets."
        )
    return {
        "User-Agent": f"IPO Alert {contact_email}",
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
        List of dicts with keys: company_name, filing_date, accession_number, cik, filing_type
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
    seen_accessions: set[str] = set()
    batch_size = 40

    while True:
        try:
            response = requests.get(
                EDGAR_SEARCH_URL, params=params, headers=_get_headers(), timeout=30
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
            form_type = source.get("form", "")

            # Only original S-1s, not amendments (S-1/A)
            if form_type != "S-1":
                continue

            ciks = source.get("ciks", [])
            raw_cik = ciks[0] if ciks else ""
            # Strip leading zeros for URL usage
            cik = str(int(raw_cik)) if raw_cik.isdigit() else raw_cik

            # display_names format: "Company Name  (TICKER)  (CIK 0001234567)"
            display_names = source.get("display_names", [])
            raw_name = display_names[0] if display_names else "Unknown"
            company_name = raw_name.split("(")[0].strip() if "(" in raw_name else raw_name

            accession_number = source.get("adsh", "")
            if accession_number in seen_accessions:
                continue
            seen_accessions.add(accession_number)

            filings.append({
                "company_name": company_name,
                "filing_date": source.get("file_date", ""),
                "accession_number": accession_number,
                "cik": cik,
                "filing_type": "S-1",
            })

        from_val = params["from"] + len(hits)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        if from_val >= total:
            break

        params["from"] = from_val
        time.sleep(0.4)  # Be respectful of EDGAR rate limits

    return filings


def get_s1a_filings(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch S-1/A (amendment) filings from EDGAR for a given date range.

    Args:
        start_date: YYYY-MM-DD format
        end_date:   YYYY-MM-DD format

    Returns:
        List of dicts with keys: company_name, filing_date, accession_number, cik, filing_type
    """
    params = {
        "q": '""',
        "forms": "S-1/A",
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "hits.hits.total.value": "true",
        "from": 0,
    }

    filings = []
    seen_accessions: set[str] = set()
    batch_size = 40

    while True:
        try:
            response = requests.get(
                EDGAR_SEARCH_URL, params=params, headers=_get_headers(), timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"  [EDGAR] Error fetching S-1/A filings: {e}")
            break

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            form_type = source.get("form", "")

            # Only S-1/A amendments, not original S-1s
            if form_type != "S-1/A":
                continue

            ciks = source.get("ciks", [])
            raw_cik = ciks[0] if ciks else ""
            cik = str(int(raw_cik)) if raw_cik.isdigit() else raw_cik

            display_names = source.get("display_names", [])
            raw_name = display_names[0] if display_names else "Unknown"
            company_name = raw_name.split("(")[0].strip() if "(" in raw_name else raw_name

            accession_number = source.get("adsh", "")
            if accession_number in seen_accessions:
                continue
            seen_accessions.add(accession_number)

            filings.append({
                "company_name": company_name,
                "filing_date": source.get("file_date", ""),
                "accession_number": accession_number,
                "cik": cik,
                "filing_type": "S-1/A",
            })

        from_val = params["from"] + len(hits)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        if from_val >= total:
            break

        params["from"] = from_val
        time.sleep(0.4)

    return filings


def get_424b4_filings(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch 424B4 (final prospectus) filings from EDGAR for a given date range.

    Args:
        start_date: YYYY-MM-DD format
        end_date:   YYYY-MM-DD format

    Returns:
        List of dicts with keys: company_name, filing_date, accession_number, cik, filing_type
    """
    params = {
        "q": '""',
        "forms": "424B4",
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "hits.hits.total.value": "true",
        "from": 0,
    }

    filings = []
    seen_accessions: set[str] = set()

    while True:
        try:
            response = requests.get(
                EDGAR_SEARCH_URL, params=params, headers=_get_headers(), timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"  [EDGAR] Error fetching 424B4 filings: {e}")
            break

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})

            ciks = source.get("ciks", [])
            raw_cik = ciks[0] if ciks else ""
            cik = str(int(raw_cik)) if raw_cik.isdigit() else raw_cik

            display_names = source.get("display_names", [])
            raw_name = display_names[0] if display_names else "Unknown"
            company_name = raw_name.split("(")[0].strip() if "(" in raw_name else raw_name

            accession_number = source.get("adsh", "")
            if accession_number in seen_accessions:
                continue
            seen_accessions.add(accession_number)

            filings.append({
                "company_name": company_name,
                "filing_date": source.get("file_date", ""),
                "accession_number": accession_number,
                "cik": cik,
                "filing_type": "424B4",
            })

        from_val = params["from"] + len(hits)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        if from_val >= total:
            break

        params["from"] = from_val
        time.sleep(0.4)

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

    # Use data.sec.gov submissions API to get the primary document filename
    cik_padded = cik.zfill(10)
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        time.sleep(0.3)
        resp = requests.get(submissions_url, headers=_get_headers(), timeout=30)
        resp.raise_for_status()
        submissions = resp.json()
    except Exception as e:
        print(f"  [EDGAR] Could not fetch submissions for CIK {cik}: {e}")
        return None

    recent = submissions.get("filings", {}).get("recent", {})
    accession_list = recent.get("accessionNumber", [])
    try:
        idx = accession_list.index(accession_number)
    except ValueError:
        print(f"  [EDGAR] Accession {accession_number} not found in submissions for CIK {cik}")
        return None

    primary_doc = recent.get("primaryDocument", [])[idx]
    doc_url = f"{EDGAR_ARCHIVES_URL}/{cik}/{accession_no_dashes}/{primary_doc}"

    if not primary_doc:
        print(f"  [EDGAR] No primary document found for {accession_number}")
        return None

    try:
        time.sleep(0.3)
        resp = requests.get(doc_url, headers=_get_headers(), timeout=90)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [EDGAR] Error downloading filing document: {e}")
        return None


def get_filing_document_with_fallback(cik: str, accession_number: str) -> Optional[str]:
    """
    Download the primary HTML document for a filing, retrying up to 3 times
    with 1-second backoff on failure.

    Args:
        cik:              Company CIK (without leading zeros)
        accession_number: Format like "0001234567-26-000123"

    Returns:
        HTML content as string, or None after all retries are exhausted.
    """
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        result = get_filing_document(cik, accession_number)
        if result is not None:
            return result
        if attempt < max_attempts:
            print(f"  [EDGAR] Retry {attempt}/{max_attempts - 1} for {accession_number}…")
            time.sleep(1)
    return None
