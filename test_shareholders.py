"""
Unit tests for shareholder parsing, VC-backed validation, and the VC firm
reference list.
"""

import unittest

from normalize import parse_shareholders, validate_vc_backed
from vc_firms import is_vc_firm


# ---------------------------------------------------------------------------
# Tests: parse_shareholders()
# ---------------------------------------------------------------------------

class TestParseShareholders(unittest.TestCase):
    """Tests for the parse_shareholders normalization function."""

    # --- parenthesised format ---

    def test_parenthesis_format_multiple(self) -> None:
        """Semicolon-separated 'Name (X%)' entries are normalised correctly."""
        result = parse_shareholders(
            "Sequoia Capital Fund XIV (12.4%); Accel Partners (8.1%)"
        )
        self.assertEqual(result, "Sequoia Capital Fund XIV 12.4%; Accel Partners 8.1%")

    def test_parenthesis_format_single(self) -> None:
        """A single 'Name (X%)' entry is normalised correctly."""
        result = parse_shareholders("Founder Trust (22.5%)")
        self.assertEqual(result, "Founder Trust 22.5%")

    # --- em/en/hyphen dash format ---

    def test_em_dash_format(self) -> None:
        """'Name \u2014 X%' (em dash) is normalised correctly."""
        result = parse_shareholders("John Smith \u2014 8.2%")
        self.assertEqual(result, "John Smith 8.2%")

    def test_hyphen_dash_format(self) -> None:
        """'Name - X%' (ASCII hyphen) is normalised correctly."""
        result = parse_shareholders("Jane Doe - 5.0%")
        self.assertEqual(result, "Jane Doe 5.0%")

    # --- comma format ---

    def test_comma_format(self) -> None:
        """'Name, X%' is normalised correctly."""
        result = parse_shareholders("Tiger Global Management, 15%")
        self.assertEqual(result, "Tiger Global Management 15%")

    # --- colon format ---

    def test_colon_format(self) -> None:
        """'Name: X%' is normalised correctly."""
        result = parse_shareholders("Founder: 22.5%")
        self.assertEqual(result, "Founder 22.5%")

    # --- sentinel / empty inputs ---

    def test_not_found_returns_none(self) -> None:
        """The sentinel phrase 'Not found' should return None."""
        result = parse_shareholders("Not found")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self) -> None:
        """An empty string should return None."""
        result = parse_shareholders("")
        self.assertIsNone(result)

    def test_none_input_returns_none(self) -> None:
        """None input should return None."""
        result = parse_shareholders(None)
        self.assertIsNone(result)

    def test_text_with_no_percentage_returns_none(self) -> None:
        """Text with no recognisable percentage pattern should return None."""
        result = parse_shareholders("Some random text without any numbers")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests: validate_vc_backed()
# ---------------------------------------------------------------------------

class TestValidateVcBacked(unittest.TestCase):
    """Tests for the validate_vc_backed cross-check function."""

    def test_claude_yes_never_downgraded(self) -> None:
        """Claude='Yes' must never be downgraded regardless of shareholders."""
        self.assertEqual(validate_vc_backed("Yes", "John Smith 10%"), "Yes")

    def test_claude_yes_with_no_shareholders(self) -> None:
        """Claude='Yes' is preserved even when shareholders is None."""
        self.assertEqual(validate_vc_backed("Yes", None), "Yes")

    def test_claude_unknown_upgraded_when_vc_found(self) -> None:
        """Claude='Unknown' is overridden to 'Yes' when a known VC appears in shareholders."""
        self.assertEqual(
            validate_vc_backed("Unknown", "Sequoia Capital 12%"), "Yes"
        )

    def test_claude_no_upgraded_when_vc_found(self) -> None:
        """Claude='No' is overridden to 'Yes' when a known VC appears in shareholders."""
        self.assertEqual(
            validate_vc_backed("No", "Andreessen Horowitz 9.5%"), "Yes"
        )

    def test_claude_unknown_stays_unknown_when_no_vc(self) -> None:
        """Claude='Unknown' stays 'Unknown' when no VC firm is in shareholders."""
        self.assertEqual(
            validate_vc_backed("Unknown", "John Smith 10%"), "Unknown"
        )

    def test_claude_no_with_none_shareholders(self) -> None:
        """Claude='No' with no shareholders text stays 'No'."""
        self.assertEqual(validate_vc_backed("No", None), "No")

    def test_claude_no_stays_no_when_no_vc(self) -> None:
        """Claude='No' stays 'No' when shareholders text contains no known VC."""
        self.assertEqual(
            validate_vc_backed("No", "Smith Family Trust 20%"), "No"
        )

    def test_a16z_triggers_upgrade(self) -> None:
        """The 'a16z' alias should trigger an upgrade from 'Unknown' to 'Yes'."""
        self.assertEqual(
            validate_vc_backed("Unknown", "a16z 7.3%"), "Yes"
        )


# ---------------------------------------------------------------------------
# Tests: is_vc_firm()
# ---------------------------------------------------------------------------

class TestIsVcFirm(unittest.TestCase):
    """Tests for the is_vc_firm substring-match helper."""

    def test_sequoia_capital_fund(self) -> None:
        """Full fund name containing 'sequoia capital' is recognised."""
        self.assertTrue(is_vc_firm("Sequoia Capital Fund XIV"))

    def test_a16z_alias(self) -> None:
        """The 'a16z' alias is recognised."""
        self.assertTrue(is_vc_firm("a16z"))

    def test_andreessen_horowitz_full(self) -> None:
        """Full name 'Andreessen Horowitz' is recognised."""
        self.assertTrue(is_vc_firm("Andreessen Horowitz"))

    def test_individual_not_matched(self) -> None:
        """An individual's name (no VC firm substring) returns False."""
        self.assertFalse(is_vc_firm("John Smith Family Trust"))

    def test_general_atlantic(self) -> None:
        """'General Atlantic' is recognised."""
        self.assertTrue(is_vc_firm("General Atlantic"))

    def test_case_insensitive_sequoia(self) -> None:
        """Lookup is case-insensitive."""
        self.assertTrue(is_vc_firm("SEQUOIA CAPITAL"))

    def test_benchmark(self) -> None:
        """'Benchmark' is recognised."""
        self.assertTrue(is_vc_firm("Benchmark Capital Partners"))

    def test_unknown_name_returns_false(self) -> None:
        """A completely unknown entity name returns False."""
        self.assertFalse(is_vc_firm("Penguin Ventures LLC"))


if __name__ == "__main__":
    unittest.main()
