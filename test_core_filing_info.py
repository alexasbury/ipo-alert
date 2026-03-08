"""
Unit tests verifying that filing_type is properly captured and persisted
throughout the IPO Alert pipeline.

Tests cover:
  - edgar_client: all three fetch functions return filing_type in every dict
  - filing_parser: FilingData dataclass includes a filing_type field
  - database: upsert_filing() correctly stores filing_type in SQLite
"""

import sqlite3
import unittest
from dataclasses import fields
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper to build a minimal EDGAR search-index API response
# ---------------------------------------------------------------------------

def _edgar_response(form: str, accession: str = "0001234567-26-000001") -> dict:
    """Return a minimal mock payload matching the EDGAR search-index JSON shape."""
    return {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_source": {
                        "form": form,
                        "adsh": accession,
                        "file_date": "2026-01-15",
                        "ciks": ["0001234567"],
                        "display_names": ["Acme Corp  (ACME)  (CIK 0001234567)"],
                    }
                }
            ],
        }
    }


def _mock_response(form: str, accession: str = "0001234567-26-000001") -> MagicMock:
    """Return a requests.Response mock pre-loaded with EDGAR JSON."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _edgar_response(form, accession)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: edgar_client
# ---------------------------------------------------------------------------

class TestEdgarClientFilingType(unittest.TestCase):
    """Verify that each EDGAR fetch function returns filing_type in every dict."""

    @patch("edgar_client.requests.get")
    def test_get_s1_filings_contains_filing_type(self, mock_get: MagicMock) -> None:
        """get_s1_filings() must return dicts with filing_type == 'S-1'."""
        # Return one hit on first call, then empty hits to terminate pagination
        mock_get.side_effect = [
            _mock_response("S-1"),
            _mock_response_empty(),
        ]

        from edgar_client import get_s1_filings

        results = get_s1_filings("2026-01-01", "2026-01-31")

        self.assertTrue(len(results) >= 1, "Expected at least one filing")
        for filing in results:
            self.assertIn("filing_type", filing, "filing_type key missing from S-1 result")
            self.assertEqual(filing["filing_type"], "S-1")

    @patch("edgar_client.requests.get")
    def test_get_s1a_filings_contains_filing_type(self, mock_get: MagicMock) -> None:
        """get_s1a_filings() must return dicts with filing_type == 'S-1/A'."""
        mock_get.side_effect = [
            _mock_response("S-1/A", "0001234567-26-000002"),
            _mock_response_empty(),
        ]

        from edgar_client import get_s1a_filings

        results = get_s1a_filings("2026-01-01", "2026-01-31")

        self.assertTrue(len(results) >= 1, "Expected at least one filing")
        for filing in results:
            self.assertIn("filing_type", filing, "filing_type key missing from S-1/A result")
            self.assertEqual(filing["filing_type"], "S-1/A")

    @patch("edgar_client.requests.get")
    def test_get_424b4_filings_contains_filing_type(self, mock_get: MagicMock) -> None:
        """get_424b4_filings() must return dicts with filing_type == '424B4'."""
        mock_get.side_effect = [
            _mock_response("424B4", "0001234567-26-000003"),
            _mock_response_empty(),
        ]

        from edgar_client import get_424b4_filings

        results = get_424b4_filings("2026-01-01", "2026-01-31")

        self.assertTrue(len(results) >= 1, "Expected at least one filing")
        for filing in results:
            self.assertIn("filing_type", filing, "filing_type key missing from 424B4 result")
            self.assertEqual(filing["filing_type"], "424B4")


def _mock_response_empty() -> MagicMock:
    """Return a mock that causes pagination to terminate (empty hits list)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: FilingData dataclass
# ---------------------------------------------------------------------------

class TestFilingDataDataclass(unittest.TestCase):
    """Verify that FilingData includes a filing_type field."""

    def test_filing_type_field_exists(self) -> None:
        """FilingData dataclass must declare a filing_type field."""
        from filing_parser import FilingData

        field_names = {f.name for f in fields(FilingData)}
        self.assertIn(
            "filing_type",
            field_names,
            "FilingData is missing the filing_type field",
        )

    def test_filing_type_default_is_s1(self) -> None:
        """FilingData.filing_type should default to 'S-1' when not supplied."""
        from filing_parser import FilingData

        fd = FilingData(
            company_name="Acme Corp",
            filing_date="2026-01-15",
            accession_number="0001234567-26-000001",
            cik="1234567",
            transfer_agent="Acme Transfer",
            legal_counsel="Acme Law",
            dually_listed="Single class",
            lock_up_date="2026-01-15",
            lock_up_expiration_date="2026-07-14",
            lock_up_terms="180-day lock-up",
            top_5_percent_shareholders="Founder: 60%",
            top_5_percent_shareholders_footnotes="",
            is_venture_backed="No",
        )
        self.assertEqual(fd.filing_type, "S-1")

    def test_filing_type_roundtrips_via_to_dict(self) -> None:
        """filing_type must be present in the dict returned by to_dict()."""
        from filing_parser import FilingData

        fd = FilingData(
            company_name="Acme Corp",
            filing_date="2026-01-15",
            accession_number="0001234567-26-000001",
            cik="1234567",
            transfer_agent="Acme Transfer",
            legal_counsel="Acme Law",
            dually_listed="Single class",
            lock_up_date="2026-01-15",
            lock_up_expiration_date="2026-07-14",
            lock_up_terms="180-day lock-up",
            top_5_percent_shareholders="Founder: 60%",
            top_5_percent_shareholders_footnotes="",
            is_venture_backed="No",
            filing_type="424B4",
        )
        d = fd.to_dict()
        self.assertIn("filing_type", d)
        self.assertEqual(d["filing_type"], "424B4")


# ---------------------------------------------------------------------------
# Tests: upsert_filing stores filing_type
# ---------------------------------------------------------------------------

class TestUpsertFilingStoresFilingType(unittest.TestCase):
    """Verify that upsert_filing() writes filing_type to the database."""

    def setUp(self) -> None:
        """Create a fresh temporary on-disk database for each test."""
        import os
        import tempfile
        from database import init_db

        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        init_db(self._db_path)

    def tearDown(self) -> None:
        import os
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def _query_row(self, cik: str) -> sqlite3.Row | None:
        """Open a fresh connection, fetch and return the row for this CIK."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ipo_filings WHERE cik = ?", (cik,)
        ).fetchone()
        conn.close()
        return row

    def _upsert(self, filing: dict) -> str:
        """Call upsert_filing against the temp database."""
        from database import upsert_filing
        return upsert_filing(filing, db_path=self._db_path)

    def _base_filing(self, filing_type: str, cik: str = "9999001") -> dict:
        return {
            "company_name": "Test Corp",
            "filing_date": "2026-01-15",
            "accession_number": f"0009999001-26-{cik[-3:]}001",
            "cik": cik,
            "filing_type": filing_type,
            "document_priority": filing_type,
            "transfer_agent": None,
            "legal_counsel": None,
            "dually_listed": None,
            "lock_up_date": None,
            "lock_up_expiration_date": None,
            "lock_up_terms": None,
            "top_5_percent_shareholders": None,
            "top_5_percent_shareholders_footnotes": None,
            "is_venture_backed": None,
        }

    def test_upsert_stores_s1_filing_type(self) -> None:
        """filing_type 'S-1' must be persisted on insert."""
        filing = self._base_filing("S-1", cik="9999001")
        outcome = self._upsert(filing)

        self.assertEqual(outcome, "inserted")
        row = self._query_row("9999001")
        self.assertIsNotNone(row)
        self.assertEqual(row["filing_type"], "S-1")

    def test_upsert_stores_s1a_filing_type(self) -> None:
        """filing_type 'S-1/A' must be persisted on insert."""
        filing = self._base_filing("S-1/A", cik="9999002")
        outcome = self._upsert(filing)

        self.assertEqual(outcome, "inserted")
        row = self._query_row("9999002")
        self.assertIsNotNone(row)
        self.assertEqual(row["filing_type"], "S-1/A")

    def test_upsert_stores_424b4_filing_type(self) -> None:
        """filing_type '424B4' must be persisted on insert."""
        filing = self._base_filing("424B4", cik="9999003")
        outcome = self._upsert(filing)

        self.assertEqual(outcome, "inserted")
        row = self._query_row("9999003")
        self.assertIsNotNone(row)
        self.assertEqual(row["filing_type"], "424B4")

    def test_upsert_updates_filing_type_on_higher_priority(self) -> None:
        """filing_type must be updated when a higher-priority filing upserts an existing row."""
        # Insert S-1 first
        s1_filing = self._base_filing("S-1", cik="9999004")
        self._upsert(s1_filing)

        # Upsert a 424B4 for the same CIK
        b4_filing = {**s1_filing, "filing_type": "424B4", "document_priority": "424B4"}
        outcome = self._upsert(b4_filing)

        self.assertEqual(outcome, "updated")
        row = self._query_row("9999004")
        self.assertIsNotNone(row)
        self.assertEqual(row["filing_type"], "424B4")

    def test_upsert_skips_lower_priority(self) -> None:
        """A lower-priority filing must not overwrite an existing higher-priority one."""
        # Insert 424B4 first
        b4_filing = self._base_filing("424B4", cik="9999005")
        self._upsert(b4_filing)

        # Attempt to upsert an S-1 for the same CIK
        s1_filing = {**b4_filing, "filing_type": "S-1", "document_priority": "S-1"}
        outcome = self._upsert(s1_filing)

        self.assertEqual(outcome, "skipped")
        row = self._query_row("9999005")
        # filing_type must remain 424B4
        self.assertEqual(row["filing_type"], "424B4")


if __name__ == "__main__":
    unittest.main()
