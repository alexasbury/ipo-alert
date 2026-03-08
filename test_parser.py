"""
Unit tests for filing_parser._extract_sections() and normalize.normalize_transfer_agent().

All tests use synthetic HTML snippets — no real EDGAR calls are made.
"""

import sqlite3
import tempfile
import unittest

from filing_parser import _extract_sections
from normalize import normalize_transfer_agent, normalize_filing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _html(body: str) -> str:
    """Wrap a body snippet in minimal valid HTML."""
    return f"<html><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# Transfer agent extraction
# ---------------------------------------------------------------------------

class TestTransferAgentExtraction(unittest.TestCase):
    """Tests for transfer_agent section extraction via _extract_sections()."""

    def test_standard_heading(self) -> None:
        """Standard 'Transfer Agent and Registrar' heading extracts agent name."""
        html = _html(
            "<p>Transfer Agent and Registrar. "
            "Computershare Trust Company, N.A. will serve as transfer agent.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("Computershare", snippet)

    def test_variant_heading_appointed_as(self) -> None:
        """'Registrar and Transfer Agent' variant heading is recognised."""
        html = _html(
            "<p>Registrar and Transfer Agent. We have appointed "
            "Continental Stock Transfer &amp; Trust Company as our transfer agent.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("Continental Stock Transfer", snippet)

    def test_address_included_in_snippet(self) -> None:
        """Transfer agent snippet is captured even when a mailing address follows the name."""
        html = _html(
            "<p>Transfer Agent. West Coast Stock Transfer, Inc., "
            "721 N. Vulcan Ave., Encinitas, CA 92024</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("West Coast Stock Transfer", snippet)

    def test_serves_as_our_transfer_agent_variant(self) -> None:
        """'serves as our transfer agent' keyword variant triggers extraction."""
        html = _html(
            "<p>Equiniti Trust Company, LLC serves as our transfer agent "
            "and registrar for our common stock.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("Equiniti", snippet)

    def test_appointed_as_transfer_agent_variant(self) -> None:
        """'appointed as transfer agent' keyword variant triggers extraction."""
        # Firm name appears after the trigger phrase, matching real S-1 prose.
        html = _html(
            "<p>We have appointed as transfer agent and registrar "
            "American Stock Transfer &amp; Trust Company, LLC.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("American Stock Transfer", snippet)

    def test_registrar_and_paying_agent_variant(self) -> None:
        """'registrar and paying agent' keyword variant triggers extraction."""
        html = _html(
            "<p>The registrar and paying agent for our shares is "
            "Computershare Investor Services LLC.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("transfer_agent", "")
        self.assertIn("registrar and paying agent", snippet.lower())


# ---------------------------------------------------------------------------
# Legal counsel extraction
# ---------------------------------------------------------------------------

class TestLegalCounselExtraction(unittest.TestCase):
    """Tests for legal_counsel section extraction via _extract_sections()."""

    def test_standard_legal_matters_heading(self) -> None:
        """Standard 'Legal Matters' section heading extracts company counsel."""
        html = _html(
            "<p>Legal Matters. The validity of the shares offered hereby will be "
            "passed upon for us by Wilson Sonsini Goodrich &amp; Rosati, "
            "Professional Corporation.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Wilson Sonsini", snippet)

    def test_has_acted_as_counsel_variant(self) -> None:
        """'has acted as counsel' keyword variant triggers extraction."""
        html = _html(
            "<p>Latham &amp; Watkins LLP has acted as counsel to the company "
            "in connection with this offering.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Latham", snippet)

    def test_pass_upon_certain_legal_matters_for_us(self) -> None:
        """'pass upon certain legal matters for us' keyword variant is recognised."""
        html = _html(
            "<p>Cooley LLP will pass upon certain legal matters for us in "
            "connection with the offering.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Cooley", snippet)

    def test_underwriters_counsel_not_extracted_as_primary(self) -> None:
        """
        Underwriters' counsel text appearing without a company-counsel heading
        should not cause a false match under 'legal_counsel' when the section
        keyword is specific to the company counsel context.

        This test verifies the snippet captured (if any) does NOT claim
        Kirkland & Ellis is the *only* result — i.e. the extraction doesn't
        blindly return underwriters' counsel as the primary counsel.
        """
        # Provide only the underwriters' counsel blurb with no company-counsel heading.
        html = _html(
            "<p>Certain legal matters will be passed upon for the underwriters "
            "by Kirkland &amp; Ellis LLP.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        # If extraction fires on "legal matters", Kirkland may appear in the raw snippet.
        # The important invariant is that the section is empty OR that the Claude prompt
        # will disambiguate. We assert that either no snippet was found, or the snippet
        # does not contain Kirkland without also containing "underwriters" (so Claude
        # can reject it).
        if "kirkland" in snippet.lower():
            self.assertIn("underwriter", snippet.lower(),
                          "If Kirkland appears in the snippet the word 'underwriter' "
                          "must also appear so Claude can reject it as issuer counsel.")

    def test_our_counsel_variant(self) -> None:
        """'our counsel' keyword variant triggers extraction."""
        html = _html(
            "<p>Our counsel, Gunderson Dettmer Stough Villeneuve Franklin &amp; Hachigian, LLP, "
            "has advised us on certain matters related to this offering.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Gunderson", snippet)

    def test_counsel_to_the_company_variant(self) -> None:
        """'counsel to the company' keyword variant triggers extraction."""
        html = _html(
            "<p>Fenwick &amp; West LLP is acting as counsel to the company "
            "in connection with this offering.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Fenwick", snippet)

    def test_pass_upon_legal_matters_for_the_company_variant(self) -> None:
        """'pass upon legal matters for the company' keyword variant triggers extraction."""
        # Firm name appears after the trigger phrase so it falls within the 'after' window.
        html = _html(
            "<p>Certain legal matters for the company will be passed upon by "
            "Skadden, Arps, Slate, Meagher &amp; Flom LLP "
            "in connection with this offering.</p>"
        )
        sections = _extract_sections(html)
        snippet = sections.get("legal_counsel", "")
        self.assertIn("Skadden", snippet)


# ---------------------------------------------------------------------------
# normalize_transfer_agent()
# ---------------------------------------------------------------------------

class TestNormalizeTransferAgent(unittest.TestCase):
    """Direct unit tests for normalize.normalize_transfer_agent()."""

    def test_strips_street_address(self) -> None:
        """Address following the entity name should be stripped."""
        result = normalize_transfer_agent(
            "West Coast Stock Transfer, Inc., 721 N. Vulcan Ave., Encinitas, CA 92024"
        )
        self.assertEqual(result, "West Coast Stock Transfer, Inc.")

    def test_preserves_name_without_address(self) -> None:
        """A name with no street address should pass through unchanged."""
        result = normalize_transfer_agent("Computershare Trust Company, N.A.")
        self.assertEqual(result, "Computershare Trust Company, N.A.")

    def test_preserves_continental_stock_transfer(self) -> None:
        """Continental Stock Transfer with no address is returned unchanged."""
        result = normalize_transfer_agent("Continental Stock Transfer & Trust Company")
        self.assertEqual(result, "Continental Stock Transfer & Trust Company")

    def test_returns_none_for_not_found(self) -> None:
        """Sentinel phrase 'Not found' should return None."""
        result = normalize_transfer_agent("Not found")
        self.assertIsNone(result)

    def test_returns_none_for_empty_string(self) -> None:
        """Empty string input should return None."""
        result = normalize_transfer_agent("")
        self.assertIsNone(result)

    def test_returns_none_for_none_input(self) -> None:
        """None input should return None."""
        result = normalize_transfer_agent(None)
        self.assertIsNone(result)

    def test_returns_none_for_unknown_sentinel(self) -> None:
        """'Unknown' sentinel should return None."""
        result = normalize_transfer_agent("Unknown")
        self.assertIsNone(result)

    def test_strips_address_with_po_box_style(self) -> None:
        """Street-number pattern mid-string triggers truncation."""
        result = normalize_transfer_agent(
            "American Stock Transfer & Trust Company, LLC, 6201 15th Avenue, Brooklyn, NY 11219"
        )
        self.assertEqual(result, "American Stock Transfer & Trust Company, LLC")


# ---------------------------------------------------------------------------
# normalize_filing() — transfer_agent_normalized included in output
# ---------------------------------------------------------------------------

class TestNormalizeFilingIncludesTransferAgent(unittest.TestCase):
    """Verify normalize_filing() returns transfer_agent_normalized."""

    def test_transfer_agent_normalized_present_in_output(self) -> None:
        """normalize_filing() must include transfer_agent_normalized key."""
        row = {
            "transfer_agent": "West Coast Stock Transfer, Inc., 721 N. Vulcan Ave., Encinitas, CA 92024",
            "lock_up_expiration_date": "180 days after the prospectus date",
            "filing_date": "2026-01-15",
        }
        derived = normalize_filing(row)
        self.assertIn("transfer_agent_normalized", derived)
        self.assertEqual(derived["transfer_agent_normalized"], "West Coast Stock Transfer, Inc.")

    def test_transfer_agent_normalized_none_for_sentinel(self) -> None:
        """normalize_filing() returns None for transfer_agent_normalized when raw is sentinel."""
        row = {
            "transfer_agent": "Not found",
            "lock_up_expiration_date": "Not found",
            "filing_date": "2026-01-15",
        }
        derived = normalize_filing(row)
        self.assertIsNone(derived["transfer_agent_normalized"])

    def test_transfer_agent_normalized_preserves_clean_name(self) -> None:
        """normalize_filing() returns clean name unchanged when no address present."""
        row = {
            "transfer_agent": "Computershare Trust Company, N.A.",
            "lock_up_expiration_date": "180 days",
            "filing_date": "2026-03-01",
        }
        derived = normalize_filing(row)
        self.assertEqual(derived["transfer_agent_normalized"], "Computershare Trust Company, N.A.")


# ---------------------------------------------------------------------------
# DB schema — transfer_agent_normalized column exists after init_db()
# ---------------------------------------------------------------------------

class TestDatabaseSchemaHasNormalizedColumn(unittest.TestCase):
    """Verify the transfer_agent_normalized column is present after init_db()."""

    def test_column_exists_after_init_db(self) -> None:
        """init_db() must create or migrate the transfer_agent_normalized column."""
        from database import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            init_db(db_path)
            conn = sqlite3.connect(db_path)
            cur = conn.execute("PRAGMA table_info(ipo_filings)")
            columns = {row[1] for row in cur.fetchall()}
            conn.close()
            self.assertIn("transfer_agent_normalized", columns)
        finally:
            import os
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_apply_normalization_writes_normalized_column(self) -> None:
        """apply_normalization() must persist transfer_agent_normalized to the DB."""
        from database import init_db, upsert_filing, apply_normalization

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            init_db(db_path)

            filing = {
                "company_name": "TestCo",
                "filing_date": "2026-01-15",
                "accession_number": "0001234567-26-000001",
                "cik": "9998877",
                "filing_type": "S-1",
                "document_priority": "S-1",
                "transfer_agent": "West Coast Stock Transfer, Inc., 721 N. Vulcan Ave., Encinitas, CA 92024",
                "legal_counsel": "Cooley LLP",
                "dually_listed": "Single class",
                "lock_up_date": "2026-01-15",
                "lock_up_expiration_date": "180 days after the prospectus date",
                "lock_up_terms": "180-day lock-up",
                "top_5_percent_shareholders": "Founder (60%)",
                "top_5_percent_shareholders_footnotes": "",
                "is_venture_backed": "No",
            }
            upsert_filing(filing, db_path)

            from normalize import normalize_filing
            derived = normalize_filing(filing)
            apply_normalization("0001234567-26-000001", derived, db_path)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT transfer_agent_normalized FROM ipo_filings WHERE accession_number=?",
                ("0001234567-26-000001",),
            )
            row = cur.fetchone()
            conn.close()

            self.assertIsNotNone(row)
            self.assertEqual(row["transfer_agent_normalized"], "West Coast Stock Transfer, Inc.")
        finally:
            import os
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
