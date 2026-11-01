"""Unit tests for Canonical Unicode and Diacritics Normalizer."""

import unittest
import unicodedata
from code.src.logging_agent.normalizer import (
    normalize_text_nfc,
    strip_accents,
    get_name_variants,
)


class TestUnicodeNormalizer(unittest.TestCase):
    """Verifies NFC composition, accent-stripping, and variant generation."""

    def test_composed_vs_decomposed_nfc(self) -> None:
        """NFC composition must reconcile composed and decomposed Unicode representations."""
        # 'e' + combining acute accent (\u0301) vs composed 'é' (\u00e9)
        decomposed = "Le" + "\u0301" + "onie"
        composed = "Léonie"
        self.assertNotEqual(decomposed, composed)
        self.assertEqual(normalize_text_nfc(decomposed), normalize_text_nfc(composed))

    def test_strip_accents_international_names(self) -> None:
        """Accented international names must reduce to clean ASCII-folded aliases."""
        test_cases = [
            ("Sofía Fernández", "sofia fernandez"),
            ("João Santos", "joao santos"),
            ("Léonie Girard", "leonie girard"),
            ("Marek Zieliński", "marek zielinski"),
            ("Zofia Dvořák", "zofia dvorak"),
            ("Freja Nyström", "freja nystrom"),
        ]
        for original, expected in test_cases:
            stripped = strip_accents(original)
            self.assertEqual(stripped, expected, f"Failed for name: {original}")

    def test_get_name_variants(self) -> None:
        """Both accented NFC and accent-stripped aliases must be produced."""
        variants = get_name_variants("Sofía Fernández")
        self.assertIn("sofía fernández", variants)
        self.assertIn("sofia fernandez", variants)
        self.assertEqual(len(variants), 2)


if __name__ == "__main__":
    unittest.main()
