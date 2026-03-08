"""
Unit tests for normalize.py.

Covers:
  - parse_lock_up_days()
  - compute_lock_up_expires_on()
  - normalize_filing()
"""

import unittest

from normalize import compute_lock_up_expires_on, normalize_filing, parse_lock_up_days


# ---------------------------------------------------------------------------
# Tests: parse_lock_up_days
# ---------------------------------------------------------------------------

class TestParseLockUpDays(unittest.TestCase):
    """Tests for the lock-up duration parser."""

    # --- Numeric day patterns ---

    def test_numeric_days_plain(self) -> None:
        """'180 days' should return 180."""
        self.assertEqual(parse_lock_up_days("180 days"), 180)

    def test_numeric_days_hyphenated_with_context(self) -> None:
        """'180-day lock-up period' should return 180."""
        self.assertEqual(parse_lock_up_days("180-day lock-up period"), 180)

    def test_numeric_days_90(self) -> None:
        """'90 day' (no trailing s) should return 90."""
        self.assertEqual(parse_lock_up_days("90 day"), 90)

    # --- Numeric month patterns ---

    def test_numeric_months_6(self) -> None:
        """'6 months' should return 180 (6 × 30)."""
        self.assertEqual(parse_lock_up_days("6 months"), 180)

    def test_numeric_months_12(self) -> None:
        """'12 months' should return 360 (12 × 30)."""
        self.assertEqual(parse_lock_up_days("12 months"), 360)

    # --- Written-out month patterns ---

    def test_written_six_months(self) -> None:
        """'six months' should return 180."""
        self.assertEqual(parse_lock_up_days("six months"), 180)

    def test_written_twelve_months(self) -> None:
        """'twelve months' should return 360."""
        self.assertEqual(parse_lock_up_days("twelve months"), 360)

    def test_written_eighteen_months(self) -> None:
        """'eighteen months' should return 540 (18 × 30)."""
        self.assertEqual(parse_lock_up_days("eighteen months"), 540)

    def test_written_three_months(self) -> None:
        """'three months' should return 90 (3 × 30)."""
        self.assertEqual(parse_lock_up_days("three months"), 90)

    def test_written_three_month_hyphenated(self) -> None:
        """'three-month lock-up' should return 90."""
        self.assertEqual(parse_lock_up_days("three-month lock-up"), 90)

    def test_written_four_months(self) -> None:
        """'four months' should return 120 (4 × 30)."""
        self.assertEqual(parse_lock_up_days("four months"), 120)

    def test_written_four_month_hyphenated(self) -> None:
        """'four-month period' should return 120."""
        self.assertEqual(parse_lock_up_days("four-month period"), 120)

    # --- Written-out year patterns ---

    def test_one_year(self) -> None:
        """'one year' should return 365."""
        self.assertEqual(parse_lock_up_days("one year"), 365)

    def test_two_years(self) -> None:
        """'two years' should return 730."""
        self.assertEqual(parse_lock_up_days("two years"), 730)

    def test_one_year_hyphenated(self) -> None:
        """'one-year lock-up' should return 365."""
        self.assertEqual(parse_lock_up_days("one-year lock-up"), 365)

    def test_two_year_hyphenated(self) -> None:
        """'two-year restriction period' should return 730."""
        self.assertEqual(parse_lock_up_days("two-year restriction period"), 730)

    # --- Sentinel / unrecognised inputs ---

    def test_sentinel_not_found(self) -> None:
        """'Not found' sentinel should return None."""
        self.assertIsNone(parse_lock_up_days("Not found"))

    def test_sentinel_pending_ipo(self) -> None:
        """'Pending IPO' sentinel should return None."""
        self.assertIsNone(parse_lock_up_days("Pending IPO"))

    def test_empty_string(self) -> None:
        """Empty string should return None."""
        self.assertIsNone(parse_lock_up_days(""))

    def test_none_input(self) -> None:
        """None input should return None without raising."""
        self.assertIsNone(parse_lock_up_days(None))

    def test_unrecognised_text(self) -> None:
        """Arbitrary non-matching text should return None."""
        self.assertIsNone(parse_lock_up_days("subject to customary exceptions"))


# ---------------------------------------------------------------------------
# Tests: compute_lock_up_expires_on
# ---------------------------------------------------------------------------

class TestComputeLockUpExpiresOn(unittest.TestCase):
    """Tests for the lock-up expiry date calculator."""

    def test_normal_calculation(self) -> None:
        """prospectus_date + 180 days should equal 2025-07-14."""
        self.assertEqual(
            compute_lock_up_expires_on("2025-01-15", 180),
            "2025-07-14",
        )

    def test_none_prospectus_date(self) -> None:
        """None prospectus_date should return None, regardless of lock_up_days."""
        self.assertIsNone(compute_lock_up_expires_on(None, 180))

    def test_none_lock_up_days(self) -> None:
        """None lock_up_days should return None even when prospectus_date is valid."""
        self.assertIsNone(compute_lock_up_expires_on("2025-01-15", None))

    def test_invalid_date_string(self) -> None:
        """An unparseable date string should return None gracefully (no exception)."""
        self.assertIsNone(compute_lock_up_expires_on("invalid-date", 180))

    def test_filing_date_not_used_as_fallback(self) -> None:
        """
        Passing prospectus_date=None with a real filing_date in the row dict
        should still return None — filing_date must NOT be used as a fallback
        inside compute_lock_up_expires_on itself.
        """
        # compute_lock_up_expires_on only accepts positional args, so
        # there is no way for filing_date to leak in.
        result = compute_lock_up_expires_on(None, 180)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests: normalize_filing (integration / wrapper)
# ---------------------------------------------------------------------------

class TestNormalizeFiling(unittest.TestCase):
    """Tests for the normalize_filing convenience wrapper."""

    def test_row_with_prospectus_date_computes_expiry(self) -> None:
        """
        A row that has a prospectus_date and a parseable lock_up_expiration_date
        should produce correct lock_up_days and lock_up_expires_on.
        """
        row = {
            "prospectus_date": "2025-01-15",
            "lock_up_expiration_date": "180 days after the date of the prospectus",
            "filing_date": "2024-11-01",  # must NOT be used
        }
        result = normalize_filing(row)
        self.assertEqual(result["lock_up_days"], 180)
        self.assertEqual(result["lock_up_expires_on"], "2025-07-14")

    def test_row_without_prospectus_date_returns_none_expiry(self) -> None:
        """
        A pre-IPO row with no prospectus_date should yield lock_up_expires_on=None
        even when lock_up_expiration_date contains a parseable duration.
        The filing_date must not be used as a fallback.
        """
        row = {
            "prospectus_date": None,
            "lock_up_expiration_date": "180 days after the date of the prospectus",
            "filing_date": "2024-11-01",
        }
        result = normalize_filing(row)
        self.assertEqual(result["lock_up_days"], 180)
        self.assertIsNone(result["lock_up_expires_on"])

    def test_row_missing_prospectus_date_key_returns_none_expiry(self) -> None:
        """
        A row where prospectus_date key is absent entirely should also yield None.
        """
        row = {
            "lock_up_expiration_date": "90 days",
            "filing_date": "2024-06-01",
        }
        result = normalize_filing(row)
        self.assertEqual(result["lock_up_days"], 90)
        self.assertIsNone(result["lock_up_expires_on"])

    def test_filing_date_not_used_as_fallback_in_normalize_filing(self) -> None:
        """
        Explicitly confirm that passing prospectus_date=None (with a valid
        filing_date present) produces lock_up_expires_on=None, not a date
        derived from filing_date.
        """
        row = {
            "prospectus_date": None,
            "filing_date": "2025-03-01",
            "lock_up_expiration_date": "180 days",
        }
        result = normalize_filing(row)
        self.assertIsNone(result["lock_up_expires_on"])

    def test_row_with_unrecognised_duration_text(self) -> None:
        """
        A row whose lock_up_expiration_date cannot be parsed should produce
        lock_up_days=None and lock_up_expires_on=None.
        """
        row = {
            "prospectus_date": "2025-01-15",
            "lock_up_expiration_date": "Not found",
        }
        result = normalize_filing(row)
        self.assertIsNone(result["lock_up_days"])
        self.assertIsNone(result["lock_up_expires_on"])


if __name__ == "__main__":
    unittest.main()
