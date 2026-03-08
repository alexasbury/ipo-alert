"""
Unit tests for database.py.

All tests use temporary on-disk SQLite databases (via tempfile) so that
database.py's standard sqlite3.connect(path) calls work without modification.
Each test class creates a fresh temp file in setUp and removes it in tearDown.

Covers:
  - init_db()               — creates table with all expected columns
  - upsert_filing()         — insert / update / skip logic
  - get_filings_for_email() — date-range filter and ordering
  - apply_normalization()   — writes lock_up_days, lock_up_expires_on,
                               transfer_agent_normalized, is_venture_backed_validated
  - audit_db()              — runs without error on an empty database
  - get_all_filings()       — returns all inserted rows
"""

import os
import sqlite3
import tempfile
import unittest

from database import (
    apply_normalization,
    audit_db,
    get_all_filings,
    get_filings_for_email,
    init_db,
    upsert_filing,
)

# ---------------------------------------------------------------------------
# Expected schema columns (complete set, order-independent)
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS: set[str] = {
    "id",
    "company_name",
    "filing_date",
    "accession_number",
    "cik",
    "filing_type",
    "transfer_agent",
    "transfer_agent_normalized",
    "legal_counsel",
    "dually_listed",
    "lock_up_date",
    "lock_up_expiration_date",
    "lock_up_terms",
    "top_5_percent_shareholders",
    "top_5_percent_shareholders_footnotes",
    "is_venture_backed",
    "is_venture_backed_validated",
    "prospectus_date",
    "document_priority",
    "lock_up_days",
    "lock_up_expires_on",
    "created_at",
}


# ---------------------------------------------------------------------------
# Helper fixture
# ---------------------------------------------------------------------------

def _make_filing(
    cik: str = "1000001",
    company_name: str = "Test Corp",
    filing_type: str = "S-1",
    filing_date: str = "2026-01-15",
    accession_number: str = "0001234567-26-000001",
    prospectus_date: str | None = None,
) -> dict:
    """Return a minimal valid filing dict for use across tests."""
    return {
        "company_name": company_name,
        "filing_date": filing_date,
        "accession_number": accession_number,
        "cik": cik,
        "filing_type": filing_type,
        "document_priority": filing_type,
        "transfer_agent": "Computershare Trust Company, N.A., 150 Royall St",
        "legal_counsel": "Latham & Watkins LLP",
        "dually_listed": "Single class",
        "lock_up_date": "The date of the final prospectus",
        "lock_up_expiration_date": "180 days after the date of the prospectus",
        "lock_up_terms": "180-day lock-up for directors and officers",
        "top_5_percent_shareholders": "Sequoia Capital (35%); Founder (20%)",
        "top_5_percent_shareholders_footnotes": "",
        "is_venture_backed": "Yes",
        "prospectus_date": prospectus_date,
    }


# ---------------------------------------------------------------------------
# Base class: manages a temp-file database
# ---------------------------------------------------------------------------

class TempDbTestCase(unittest.TestCase):
    """Base class that creates and tears down a temporary SQLite database."""

    def setUp(self) -> None:
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self._tmpfile.name
        self._tmpfile.close()
        init_db(self.db)

    def tearDown(self) -> None:
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def _get_row(self, cik: str) -> dict | None:
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ipo_filings WHERE cik = ?", (cik,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tests: init_db
# ---------------------------------------------------------------------------

class TestInitDb(TempDbTestCase):
    """Tests for init_db() schema creation."""

    def test_creates_table_with_all_expected_columns(self) -> None:
        """init_db() should create ipo_filings with all required columns."""
        conn = sqlite3.connect(self.db)
        cur = conn.execute("PRAGMA table_info(ipo_filings)")
        actual_columns = {row[1] for row in cur.fetchall()}
        conn.close()
        self.assertEqual(actual_columns, EXPECTED_COLUMNS)

    def test_migration_is_idempotent(self) -> None:
        """Calling init_db() a second time must not raise and preserves columns."""
        try:
            init_db(self.db)
        except Exception as e:
            self.fail(f"Second init_db() raised: {e}")

        conn = sqlite3.connect(self.db)
        cur = conn.execute("PRAGMA table_info(ipo_filings)")
        actual_columns = {row[1] for row in cur.fetchall()}
        conn.close()
        self.assertEqual(actual_columns, EXPECTED_COLUMNS)


# ---------------------------------------------------------------------------
# Tests: upsert_filing
# ---------------------------------------------------------------------------

class TestUpsertFiling(TempDbTestCase):
    """Tests for the insert/update/skip logic in upsert_filing()."""

    def test_insert_new_record_returns_inserted(self) -> None:
        """upsert_filing() should return 'inserted' for a new CIK."""
        filing = _make_filing(cik="2000001", accession_number="ACC-INSERT-1")
        result = upsert_filing(filing, self.db)
        self.assertEqual(result, "inserted")

    def test_inserted_row_is_retrievable(self) -> None:
        """Inserted filing should be stored and retrievable."""
        filing = _make_filing(cik="2000002", accession_number="ACC-INSERT-2")
        upsert_filing(filing, self.db)
        row = self._get_row("2000002")
        self.assertIsNotNone(row)
        self.assertEqual(row["company_name"], "Test Corp")
        self.assertEqual(row["document_priority"], "S-1")

    def test_update_when_higher_priority_arrives(self) -> None:
        """upsert_filing() should return 'updated' when a higher-priority filing arrives."""
        s1 = _make_filing(cik="2000003", filing_type="S-1", accession_number="ACC-S1-3")
        upsert_filing(s1, self.db)

        s1a = _make_filing(cik="2000003", filing_type="S-1/A", accession_number="ACC-S1A-3")
        result = upsert_filing(s1a, self.db)
        self.assertEqual(result, "updated")

    def test_update_preserves_original_filing_date_and_accession(self) -> None:
        """On update, original filing_date and accession_number must be preserved."""
        s1 = _make_filing(
            cik="2000004",
            filing_type="S-1",
            filing_date="2026-01-10",
            accession_number="ACC-ORIG-4",
        )
        upsert_filing(s1, self.db)

        b4 = _make_filing(
            cik="2000004",
            filing_type="424B4",
            filing_date="2026-02-01",
            accession_number="ACC-NEW-4",
        )
        upsert_filing(b4, self.db)

        row = self._get_row("2000004")
        self.assertEqual(row["accession_number"], "ACC-ORIG-4")
        self.assertEqual(row["filing_date"], "2026-01-10")
        self.assertEqual(row["document_priority"], "424B4")

    def test_skip_when_equal_priority(self) -> None:
        """upsert_filing() should return 'skipped' when incoming priority equals stored."""
        s1 = _make_filing(cik="2000005", filing_type="S-1", accession_number="ACC-S1-5")
        upsert_filing(s1, self.db)

        s1b = _make_filing(cik="2000005", filing_type="S-1", accession_number="ACC-S1-5b")
        result = upsert_filing(s1b, self.db)
        self.assertEqual(result, "skipped")

    def test_skip_when_lower_priority(self) -> None:
        """upsert_filing() should return 'skipped' when incoming priority is lower."""
        b4 = _make_filing(cik="2000006", filing_type="424B4", accession_number="ACC-B4-6")
        upsert_filing(b4, self.db)

        s1 = _make_filing(cik="2000006", filing_type="S-1", accession_number="ACC-S1-6")
        result = upsert_filing(s1, self.db)
        self.assertEqual(result, "skipped")

        row = self._get_row("2000006")
        self.assertEqual(row["document_priority"], "424B4")


# ---------------------------------------------------------------------------
# Tests: get_filings_for_email
# ---------------------------------------------------------------------------

class TestGetFilingsForEmail(TempDbTestCase):
    """Tests for get_filings_for_email()."""

    def _insert(self, cik: str, filing_date: str, acc: str) -> None:
        filing = _make_filing(cik=cik, filing_date=filing_date, accession_number=acc)
        upsert_filing(filing, self.db)

    def test_returns_filings_within_range(self) -> None:
        """Only filings within [week_start, week_end] should be returned."""
        self._insert("3000001", "2026-01-05", "ACC-E-1")   # inside range
        self._insert("3000002", "2026-01-12", "ACC-E-2")   # inside range
        self._insert("3000003", "2025-12-31", "ACC-E-3")   # before range
        self._insert("3000004", "2026-01-20", "ACC-E-4")   # after range

        results = get_filings_for_email("2026-01-01", "2026-01-15", self.db)
        ciks = {r["cik"] for r in results}
        self.assertIn("3000001", ciks)
        self.assertIn("3000002", ciks)
        self.assertNotIn("3000003", ciks)
        self.assertNotIn("3000004", ciks)

    def test_returns_empty_list_when_no_match(self) -> None:
        """get_filings_for_email() should return [] when no filings match the range."""
        self._insert("3000010", "2025-06-01", "ACC-E-10")

        results = get_filings_for_email("2026-01-01", "2026-01-31", self.db)
        self.assertEqual(results, [])

    def test_results_ordered_by_filing_date_desc(self) -> None:
        """Results should be ordered newest-first."""
        self._insert("3000020", "2026-01-03", "ACC-E-20")
        self._insert("3000021", "2026-01-10", "ACC-E-21")
        self._insert("3000022", "2026-01-07", "ACC-E-22")

        results = get_filings_for_email("2026-01-01", "2026-01-31", self.db)
        dates = [r["filing_date"] for r in results]
        self.assertEqual(dates, sorted(dates, reverse=True))


# ---------------------------------------------------------------------------
# Tests: apply_normalization
# ---------------------------------------------------------------------------

class TestApplyNormalization(TempDbTestCase):
    """Tests for apply_normalization() writing derived fields."""

    def test_writes_all_normalized_fields(self) -> None:
        """apply_normalization() should write lock_up_days, lock_up_expires_on,
        transfer_agent_normalized, and is_venture_backed_validated."""
        filing = _make_filing(
            cik="4000001",
            accession_number="ACC-NORM-1",
            prospectus_date="2026-01-15",
        )
        upsert_filing(filing, self.db)

        derived = {
            "lock_up_days": 180,
            "lock_up_expires_on": "2026-07-14",
            "transfer_agent_normalized": "Computershare Trust Company, N.A.",
            "is_venture_backed_validated": "Yes",
        }
        apply_normalization("ACC-NORM-1", derived, self.db)

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(
            "SELECT * FROM ipo_filings WHERE accession_number=?", ("ACC-NORM-1",)
        ).fetchone())
        conn.close()

        self.assertEqual(row["lock_up_days"], 180)
        self.assertEqual(row["lock_up_expires_on"], "2026-07-14")
        self.assertEqual(row["transfer_agent_normalized"], "Computershare Trust Company, N.A.")
        self.assertEqual(row["is_venture_backed_validated"], "Yes")

    def test_upgrades_is_venture_backed_when_validated_is_yes(self) -> None:
        """When is_venture_backed_validated='Yes', is_venture_backed should be set to 'Yes'."""
        filing = _make_filing(
            cik="4000002",
            accession_number="ACC-NORM-2",
        )
        filing["is_venture_backed"] = "Unknown"
        upsert_filing(filing, self.db)

        apply_normalization("ACC-NORM-2", {"is_venture_backed_validated": "Yes"}, self.db)

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(
            "SELECT is_venture_backed FROM ipo_filings WHERE accession_number=?",
            ("ACC-NORM-2",),
        ).fetchone())
        conn.close()

        self.assertEqual(row["is_venture_backed"], "Yes")


# ---------------------------------------------------------------------------
# Tests: audit_db
# ---------------------------------------------------------------------------

class TestAuditDb(TempDbTestCase):
    """Tests for audit_db()."""

    def test_runs_without_error_on_empty_database(self) -> None:
        """audit_db() should complete without raising on an empty database."""
        try:
            audit_db(self.db)
        except Exception as e:
            self.fail(f"audit_db() raised on empty database: {e}")

    def test_runs_without_error_with_data(self) -> None:
        """audit_db() should complete without raising when rows are present."""
        upsert_filing(_make_filing(cik="5000001", accession_number="ACC-AUDIT-1"), self.db)
        try:
            audit_db(self.db)
        except Exception as e:
            self.fail(f"audit_db() raised with data: {e}")


# ---------------------------------------------------------------------------
# Tests: get_all_filings
# ---------------------------------------------------------------------------

class TestGetAllFilings(TempDbTestCase):
    """Tests for get_all_filings()."""

    def test_returns_all_inserted_rows(self) -> None:
        """get_all_filings() should return all rows inserted into the database."""
        upsert_filing(_make_filing(cik="6000001", accession_number="ACC-ALL-1"), self.db)
        upsert_filing(_make_filing(cik="6000002", accession_number="ACC-ALL-2"), self.db)
        upsert_filing(_make_filing(cik="6000003", accession_number="ACC-ALL-3"), self.db)

        rows = get_all_filings(self.db)
        self.assertEqual(len(rows), 3)

    def test_returns_empty_list_on_empty_database(self) -> None:
        """get_all_filings() should return [] when no rows exist."""
        rows = get_all_filings(self.db)
        self.assertEqual(rows, [])

    def test_returned_rows_are_dicts_with_all_columns(self) -> None:
        """Each row returned by get_all_filings() should have all expected columns."""
        upsert_filing(_make_filing(cik="6000010", accession_number="ACC-ALL-10"), self.db)
        rows = get_all_filings(self.db)
        self.assertEqual(len(rows), 1)
        row_keys = set(rows[0].keys())
        self.assertEqual(row_keys, EXPECTED_COLUMNS)


if __name__ == "__main__":
    unittest.main()
