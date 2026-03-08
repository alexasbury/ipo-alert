"""
Unit tests for filing_resolver.py and the upsert logic in database.py.

All EDGAR API calls are mocked so no network access is needed.
"""

import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from filing_resolver import PRIORITY, resolve_filings_for_range, should_upsert
from database import init_db, upsert_filing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_filing(
    cik: str,
    company_name: str,
    filing_type: str,
    filing_date: str = "2026-01-15",
    accession_number: str | None = None,
) -> dict:
    """Construct a minimal filing dict that mirrors what edgar_client returns."""
    if accession_number is None:
        # Generate a deterministic accession number based on inputs
        accession_number = f"0001234567-26-{abs(hash(cik + filing_type + filing_date)) % 100000:06d}"
    return {
        "company_name": company_name,
        "filing_date": filing_date,
        "accession_number": accession_number,
        "cik": cik,
        "filing_type": filing_type,
        "document_priority": filing_type,
        "transfer_agent": "Test Agent",
        "legal_counsel": "Test Counsel",
        "dually_listed": "Single class",
        "lock_up_date": "2026-01-15",
        "lock_up_expiration_date": "180 days after prospectus",
        "lock_up_terms": "180-day lock-up",
        "top_5_percent_shareholders": "Founder (60%)",
        "top_5_percent_shareholders_footnotes": "",
        "is_venture_backed": "No",
    }


# ---------------------------------------------------------------------------
# Tests: resolve_filings_for_range
# ---------------------------------------------------------------------------

class TestResolveFilingsForRange(unittest.TestCase):
    """Tests for filing resolution logic."""

    @patch("filing_resolver.get_424b4_filings")
    @patch("filing_resolver.get_s1a_filings")
    @patch("filing_resolver.get_s1_filings")
    def test_424b4_wins_when_all_types_present(
        self, mock_s1, mock_s1a, mock_424b4
    ) -> None:
        """424B4 should be selected when S-1, S-1/A, and 424B4 all exist for the same CIK."""
        cik = "1234567"
        mock_s1.return_value = [_make_filing(cik, "Acme Corp", "S-1", "2026-01-10", "0000001-26-000001")]
        mock_s1a.return_value = [_make_filing(cik, "Acme Corp", "S-1/A", "2026-01-12", "0000001-26-000002")]
        mock_424b4.return_value = [_make_filing(cik, "Acme Corp", "424B4", "2026-01-15", "0000001-26-000003")]

        results = resolve_filings_for_range("2026-01-01", "2026-01-31")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_priority"], "424B4")
        self.assertEqual(results[0]["cik"], cik)

    @patch("filing_resolver.get_424b4_filings")
    @patch("filing_resolver.get_s1a_filings")
    @patch("filing_resolver.get_s1_filings")
    def test_most_recent_s1a_selected_when_no_424b4(
        self, mock_s1, mock_s1a, mock_424b4
    ) -> None:
        """Most recent S-1/A should win when multiple amendments exist and no 424B4 is present."""
        cik = "2345678"
        mock_s1.return_value = [_make_filing(cik, "Beta Inc", "S-1", "2026-01-05", "0000002-26-000001")]
        mock_s1a.return_value = [
            _make_filing(cik, "Beta Inc", "S-1/A", "2026-01-10", "0000002-26-000002"),
            _make_filing(cik, "Beta Inc", "S-1/A", "2026-01-20", "0000002-26-000003"),  # most recent
            _make_filing(cik, "Beta Inc", "S-1/A", "2026-01-15", "0000002-26-000004"),
        ]
        mock_424b4.return_value = []

        results = resolve_filings_for_range("2026-01-01", "2026-01-31")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_priority"], "S-1/A")
        self.assertEqual(results[0]["accession_number"], "0000002-26-000003")
        self.assertEqual(results[0]["filing_date"], "2026-01-20")

    @patch("filing_resolver.get_424b4_filings")
    @patch("filing_resolver.get_s1a_filings")
    @patch("filing_resolver.get_s1_filings")
    def test_s1_selected_when_only_s1_exists(
        self, mock_s1, mock_s1a, mock_424b4
    ) -> None:
        """Original S-1 should be used when no amendments or 424B4 exist."""
        cik = "3456789"
        mock_s1.return_value = [_make_filing(cik, "Gamma LLC", "S-1", "2026-01-08", "0000003-26-000001")]
        mock_s1a.return_value = []
        mock_424b4.return_value = []

        results = resolve_filings_for_range("2026-01-01", "2026-01-31")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_priority"], "S-1")
        self.assertEqual(results[0]["cik"], cik)

    @patch("filing_resolver.get_424b4_filings")
    @patch("filing_resolver.get_s1a_filings")
    @patch("filing_resolver.get_s1_filings")
    def test_multiple_ciks_resolved_independently(
        self, mock_s1, mock_s1a, mock_424b4
    ) -> None:
        """Each CIK should be resolved independently."""
        mock_s1.return_value = [
            _make_filing("1111111", "Alpha", "S-1", "2026-01-05", "0000011-26-000001"),
            _make_filing("2222222", "Beta", "S-1", "2026-01-05", "0000022-26-000001"),
        ]
        mock_s1a.return_value = []
        mock_424b4.return_value = [
            _make_filing("1111111", "Alpha", "424B4", "2026-01-15", "0000011-26-000002"),
        ]

        results = resolve_filings_for_range("2026-01-01", "2026-01-31")

        by_cik = {r["cik"]: r for r in results}
        self.assertEqual(len(by_cik), 2)
        self.assertEqual(by_cik["1111111"]["document_priority"], "424B4")
        self.assertEqual(by_cik["2222222"]["document_priority"], "S-1")


# ---------------------------------------------------------------------------
# Tests: should_upsert
# ---------------------------------------------------------------------------

class TestShouldUpsert(unittest.TestCase):
    """Tests for the should_upsert helper."""

    def test_higher_priority_returns_true(self) -> None:
        """Incoming 424B4 should replace existing S-1."""
        self.assertTrue(should_upsert("S-1", "424B4"))

    def test_higher_priority_s1a_over_s1(self) -> None:
        """Incoming S-1/A should replace existing S-1."""
        self.assertTrue(should_upsert("S-1", "S-1/A"))

    def test_higher_priority_424b4_over_s1a(self) -> None:
        """Incoming 424B4 should replace existing S-1/A."""
        self.assertTrue(should_upsert("S-1/A", "424B4"))

    def test_equal_priority_returns_false(self) -> None:
        """Same priority (e.g. S-1 vs S-1) should not upsert."""
        self.assertFalse(should_upsert("S-1", "S-1"))

    def test_lower_priority_returns_false(self) -> None:
        """S-1/A arriving when 424B4 is stored should not overwrite."""
        self.assertFalse(should_upsert("424B4", "S-1/A"))

    def test_s1_arriving_when_424b4_stored_returns_false(self) -> None:
        """S-1 arriving when 424B4 is stored should not overwrite."""
        self.assertFalse(should_upsert("424B4", "S-1"))

    def test_unknown_type_returns_false(self) -> None:
        """Unknown priority strings should not trigger an upsert."""
        self.assertFalse(should_upsert("S-1", "UNKNOWN"))


# ---------------------------------------------------------------------------
# Tests: upsert_filing (database layer)
# ---------------------------------------------------------------------------

class TestUpsertFiling(unittest.TestCase):
    """Tests for upsert_filing using a temporary in-memory database file."""

    def setUp(self) -> None:
        """Create a fresh temporary database for each test."""
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        init_db(self._db_path)

    def tearDown(self) -> None:
        """Remove the temporary database file."""
        import os
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def _get_row(self, cik: str) -> dict | None:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ipo_filings WHERE cik = ?", (cik,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def test_insert_new_record(self) -> None:
        """Inserting a new CIK should return 'inserted'."""
        filing = _make_filing("9000001", "NewCo", "S-1")
        result = upsert_filing(filing, self._db_path)
        self.assertEqual(result, "inserted")
        row = self._get_row("9000001")
        self.assertIsNotNone(row)
        self.assertEqual(row["document_priority"], "S-1")

    def test_s1_updated_when_s1a_arrives(self) -> None:
        """An S-1/A should overwrite an existing S-1 record."""
        s1 = _make_filing("9000002", "UpdateCo", "S-1", accession_number="ACC-S1")
        upsert_filing(s1, self._db_path)

        s1a = _make_filing("9000002", "UpdateCo", "S-1/A", accession_number="ACC-S1A")
        result = upsert_filing(s1a, self._db_path)
        self.assertEqual(result, "updated")

        row = self._get_row("9000002")
        self.assertEqual(row["document_priority"], "S-1/A")
        # Original accession_number and filing_date must be preserved
        self.assertEqual(row["accession_number"], "ACC-S1")
        self.assertEqual(row["filing_date"], s1["filing_date"])

    def test_424b4_not_overwritten_by_s1a(self) -> None:
        """A 424B4 record must not be replaced by a lower-priority S-1/A."""
        b4 = _make_filing("9000003", "PricedCo", "424B4", accession_number="ACC-B4")
        upsert_filing(b4, self._db_path)

        s1a = _make_filing("9000003", "PricedCo", "S-1/A", accession_number="ACC-S1A")
        result = upsert_filing(s1a, self._db_path)
        self.assertEqual(result, "skipped")

        row = self._get_row("9000003")
        self.assertEqual(row["document_priority"], "424B4")

    def test_424b4_not_overwritten_by_s1(self) -> None:
        """A 424B4 record must not be replaced by a lower-priority S-1."""
        b4 = _make_filing("9000004", "SkipCo", "424B4", accession_number="ACC-B4-2")
        upsert_filing(b4, self._db_path)

        s1 = _make_filing("9000004", "SkipCo", "S-1", accession_number="ACC-S1-2")
        result = upsert_filing(s1, self._db_path)
        self.assertEqual(result, "skipped")

        row = self._get_row("9000004")
        self.assertEqual(row["document_priority"], "424B4")

    def test_s1a_updated_when_424b4_arrives(self) -> None:
        """A 424B4 filing should overwrite an existing S-1/A record."""
        s1a = _make_filing("9000005", "AmendCo", "S-1/A", accession_number="ACC-S1A-3")
        upsert_filing(s1a, self._db_path)

        b4 = _make_filing("9000005", "AmendCo", "424B4", accession_number="ACC-B4-3")
        result = upsert_filing(b4, self._db_path)
        self.assertEqual(result, "updated")

        row = self._get_row("9000005")
        self.assertEqual(row["document_priority"], "424B4")
        # Original accession_number preserved
        self.assertEqual(row["accession_number"], "ACC-S1A-3")

    def test_duplicate_same_priority_skipped(self) -> None:
        """A second S-1 for the same CIK should be skipped."""
        s1 = _make_filing("9000006", "DupCo", "S-1", accession_number="ACC-DUP-1")
        upsert_filing(s1, self._db_path)

        s1b = _make_filing("9000006", "DupCo", "S-1", accession_number="ACC-DUP-2")
        result = upsert_filing(s1b, self._db_path)
        self.assertEqual(result, "skipped")


# ---------------------------------------------------------------------------
# Tests: PRIORITY constant
# ---------------------------------------------------------------------------

class TestPriorityConstant(unittest.TestCase):
    """Sanity checks on the PRIORITY dict."""

    def test_424b4_highest(self) -> None:
        self.assertGreater(PRIORITY["424B4"], PRIORITY["S-1/A"])
        self.assertGreater(PRIORITY["424B4"], PRIORITY["S-1"])

    def test_s1a_higher_than_s1(self) -> None:
        self.assertGreater(PRIORITY["S-1/A"], PRIORITY["S-1"])


if __name__ == "__main__":
    unittest.main()
