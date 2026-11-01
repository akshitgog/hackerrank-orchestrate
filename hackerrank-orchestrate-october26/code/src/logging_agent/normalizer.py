"""Canonical Unicode and Diacritics Normalizer for Logging and Audit Agents.

Ensures robust identity matching across distributed systems that store names
with NFC, NFD, uppercase, or stripped accents (e.g. Sofía Fernández vs Sofia Fernandez).
"""

import unicodedata


def normalize_text_nfc(text: str) -> str:
    """Enforces NFC canonical composition and case folding."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).strip().casefold()


def strip_accents(text: str) -> str:
    """Converts 'Sofía' -> 'sofia', 'Léonie' -> 'leonie' for fuzzy alias matching."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


def get_name_variants(name: str) -> set[str]:
    """Generates both accented and unaccented lookup keys."""
    if not name:
        return set()
    raw_norm = normalize_text_nfc(name)
    stripped = strip_accents(name)
    return {raw_norm, stripped}
