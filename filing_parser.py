"""
Parse S-1 filing documents using Claude API to extract structured IPO data.
"""

import json
import re
from dataclasses import asdict, dataclass

import anthropic
from bs4 import BeautifulSoup

client = anthropic.Anthropic()


@dataclass
class FilingData:
    company_name: str
    filing_date: str
    accession_number: str
    cik: str
    transfer_agent: str
    legal_counsel: str
    dually_listed: str
    lock_up_date: str
    lock_up_expiration_date: str
    lock_up_terms: str
    top_5_percent_shareholders: str
    top_5_percent_shareholders_footnotes: str
    is_venture_backed: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

def _extract_around(text: str, keywords: list[str], before: int = 100, after: int = 3000) -> str:
    """Return a snippet of `text` centred on the first matching keyword."""
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw.lower())
        if idx != -1:
            start = max(0, idx - before)
            end = min(len(text), idx + after)
            return text[start:end]
    return ""


def _extract_sections(html: str) -> dict[str, str]:
    """
    Parse the S-1 HTML and pull out the sections Claude needs to analyse.
    Sections are kept short to fit comfortably in a single Claude request.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse excessive whitespace
    text = re.sub(r"\s{3,}", "  ", text)

    sections: dict[str, str] = {}

    # Cover page – first ~4 000 chars usually contain the key parties
    sections["cover_page"] = text[:4000]

    sections["transfer_agent"] = _extract_around(
        text,
        ["transfer agent and registrar", "transfer agent", "registrar and transfer agent"],
        before=50,
        after=600,
    )

    sections["legal_counsel"] = _extract_around(
        text,
        ["legal matters", "validity of securities", "legal counsel", "counsel to"],
        before=50,
        after=1000,
    )

    sections["lock_up"] = _extract_around(
        text,
        ["lock-up agreements", "lock-up period", "lock up agreements", "lockup agreements"],
        before=100,
        after=3000,
    )

    sections["beneficial_ownership"] = _extract_around(
        text,
        [
            "beneficial ownership",
            "principal stockholders",
            "principal shareholders",
            "security ownership of certain",
        ],
        before=100,
        after=6000,
    )

    # Dual-class signal
    has_a = any(kw in text.lower() for kw in ["class a common stock", "class a ordinary shares", "class a shares"])
    has_b = any(kw in text.lower() for kw in ["class b common stock", "class b ordinary shares", "class b shares"])
    has_c = any(kw in text.lower() for kw in ["class c common stock", "class c ordinary shares", "class c shares"])

    if has_a and has_b and has_c:
        sections["share_class_signal"] = "CLASS_A_B_C"
    elif has_a and has_b:
        sections["share_class_signal"] = "CLASS_A_B"
    elif has_a:
        sections["share_class_signal"] = "CLASS_A_ONLY"
    else:
        sections["share_class_signal"] = "SINGLE_CLASS"

    return sections


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "transfer_agent": {
            "type": "string",
            "description": "Name of the transfer agent / registrar, or 'Not found'"
        },
        "legal_counsel": {
            "type": "string",
            "description": "Name of the company's legal counsel (not underwriters' counsel), or 'Not found'"
        },
        "dually_listed": {
            "type": "string",
            "description": "Share class description. Use: 'Single class', 'Class A only', 'Class A & Class B', or 'Class A, Class B & Class C'"
        },
        "lock_up_date": {
            "type": "string",
            "description": "Lock-up start date. For pre-IPO S-1s this is 'Pending IPO date'. If an expected date is stated, include it."
        },
        "lock_up_expiration_date": {
            "type": "string",
            "description": "Lock-up expiration. Format: 'IPO date + 180 days' or the actual date if known."
        },
        "lock_up_terms": {
            "type": "string",
            "description": "Concise summary of lock-up: who is locked up, duration, and key exceptions."
        },
        "top_5_percent_shareholders": {
            "type": "string",
            "description": "Shareholders owning 5%+ of any share class. Format: 'Name: X%; Name: Y%' separated by semicolons. Use 'Not found' if table absent."
        },
        "top_5_percent_shareholders_footnotes": {
            "type": "string",
            "description": "Relevant footnotes for the 5%+ shareholders (e.g. options included, related entities). Empty string if none."
        },
        "is_venture_backed": {
            "type": "string",
            "enum": ["Yes", "No", "Unknown"],
            "description": "Yes if a VC/growth-equity firm is among the 5%+ shareholders or identified in footnotes as such."
        }
    },
    "required": [
        "transfer_agent", "legal_counsel", "dually_listed",
        "lock_up_date", "lock_up_expiration_date", "lock_up_terms",
        "top_5_percent_shareholders", "top_5_percent_shareholders_footnotes",
        "is_venture_backed"
    ],
    "additionalProperties": False
}


def _build_prompt(company_name: str, sections: dict[str, str]) -> str:
    def sec(name: str, limit: int = 2000) -> str:
        content = sections.get(name, "Not available")
        return content[:limit] if content else "Not available"

    return f"""You are analysing an SEC S-1 registration statement (IPO filing) for **{company_name}**.

Extract the requested fields from the sections below. Return ONLY a valid JSON object matching the schema provided.

=== STRICT RULES ===
1. Rely ONLY on the text provided below. Do not use outside knowledge, internet searches, or information about events that occurred after the filing date.
2. S-1s are often preliminary. If a date, price, or term is left blank (e.g., "[ ]", "to be determined", or only a month/year is given), extract exactly what is written or state "Not specified in preliminary filing." Do not guess or estimate.
3. Do not add conversational filler. Output only the JSON object.

=== FIELD GUIDANCE ===
- **transfer_agent**: Look in the "Description of Capital Stock" section or the prospectus summary. Also check near the bottom of the filing for a "Transfer Agent and Registrar" heading.
- **legal_counsel**: The company's own counsel only — NOT the underwriters' counsel. Look on the cover page (legal representatives for the company) or the "Legal Matters" section.
- **dually_listed**: Look in "Description of Capital Stock" or the prospectus summary. Note voting rights if applicable. The share_class_signal below is a hint. Use: 'Single class', 'Class A only', 'Class A & Class B', or 'Class A, Class B & Class C'.
- **lock_up_date**: The trigger date for the lock-up (usually the date of the final prospectus). For preliminary S-1s state "The date of the final prospectus."
- **lock_up_expiration_date**: Calculate or extract the timeframe (e.g., "180 days after the date of the prospectus"). Note any early release conditions. Look in "Shares Eligible for Future Sale" or "Underwriting."
- **lock_up_terms**: Summarize the core restrictions, who is subject to the lock-up, duration, and notable exceptions or early release triggers.
- **top_5_percent_shareholders**: Look in the "Principal and Selling Stockholders" table. List any entity or person holding 5%+ prior to the offering, with their pre-offering percentage. Format: "Name (X%); Name (Y%)".
- **top_5_percent_shareholders_footnotes**: Summarize critical context from the footnotes of the principal shareholders table — particularly super-voting control, irrevocable proxies, and who holds voting/investment power for venture entities.
- **is_venture_backed**: "Yes" if prominent venture capital firms appear in the principal shareholders table. "No" otherwise.

=== COVER PAGE ===
{sec('cover_page', 2500)}

=== TRANSFER AGENT ===
{sec('transfer_agent', 600)}

=== LEGAL MATTERS ===
{sec('legal_counsel', 1000)}

=== LOCK-UP AGREEMENTS ===
{sec('lock_up', 2500)}

=== BENEFICIAL OWNERSHIP / PRINCIPAL SHAREHOLDERS ===
{sec('beneficial_ownership', 4000)}

=== SHARE CLASS SIGNAL (automated detection) ===
{sections.get('share_class_signal', 'UNKNOWN')}
"""


def _call_claude(company_name: str, sections: dict[str, str]) -> dict:
    """Call Claude Opus with structured output to extract filing fields."""
    prompt = _build_prompt(company_name, sections)

    response = client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_format=_build_pydantic_model(),
    )

    # parse() returns a parsed_output object; convert to dict
    if hasattr(response, "parsed_output") and response.parsed_output is not None:
        return response.parsed_output.model_dump()

    # Fallback: extract JSON from raw text
    raw = response.content[0].text if response.content else ""
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return _empty_extraction()


def _build_pydantic_model():
    """Build a Pydantic model for structured output."""
    from pydantic import BaseModel
    from typing import Literal

    class ExtractionResult(BaseModel):
        transfer_agent: str
        legal_counsel: str
        dually_listed: str
        lock_up_date: str
        lock_up_expiration_date: str
        lock_up_terms: str
        top_5_percent_shareholders: str
        top_5_percent_shareholders_footnotes: str
        is_venture_backed: Literal["Yes", "No", "Unknown"]

    return ExtractionResult


def _empty_extraction() -> dict:
    return {
        "transfer_agent": "Not found",
        "legal_counsel": "Not found",
        "dually_listed": "Unknown",
        "lock_up_date": "Pending IPO",
        "lock_up_expiration_date": "Pending IPO",
        "lock_up_terms": "Not found",
        "top_5_percent_shareholders": "Not found",
        "top_5_percent_shareholders_footnotes": "",
        "is_venture_backed": "Unknown",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_filing(
    company_name: str,
    filing_date: str,
    accession_number: str,
    cik: str,
    html_content: str,
) -> FilingData:
    """
    Full parsing pipeline: extract sections from HTML, then use Claude to
    pull out structured fields.
    """
    sections = _extract_sections(html_content)

    try:
        extracted = _call_claude(company_name, sections)
    except Exception as e:
        print(f"  [Claude] Extraction error for {company_name}: {e}")
        extracted = _empty_extraction()

    return FilingData(
        company_name=company_name,
        filing_date=filing_date,
        accession_number=accession_number,
        cik=cik,
        transfer_agent=extracted.get("transfer_agent", "Not found"),
        legal_counsel=extracted.get("legal_counsel", "Not found"),
        dually_listed=extracted.get("dually_listed", "Unknown"),
        lock_up_date=extracted.get("lock_up_date", "Pending IPO"),
        lock_up_expiration_date=extracted.get("lock_up_expiration_date", "Pending IPO"),
        lock_up_terms=extracted.get("lock_up_terms", "Not found"),
        top_5_percent_shareholders=extracted.get("top_5_percent_shareholders", "Not found"),
        top_5_percent_shareholders_footnotes=extracted.get(
            "top_5_percent_shareholders_footnotes", ""
        ),
        is_venture_backed=extracted.get("is_venture_backed", "Unknown"),
    )
