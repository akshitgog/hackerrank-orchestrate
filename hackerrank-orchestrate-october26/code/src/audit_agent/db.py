"""In-memory SQLite connection manager with Unicode and accent-insensitive extensions."""

import sqlite3
import unicodedata


def get_audit_db_connection() -> sqlite3.Connection:
    """Creates an in-memory SQLite connection with custom Unicode-aware functions."""
    conn = sqlite3.connect(":memory:")

    # Enable Unicode-aware case-insensitive matching
    conn.create_function("UNICODE_LOWER", 1, lambda s: s.casefold() if s else None)
    conn.create_function(
        "STRIP_ACCENTS",
        1,
        lambda s: "".join(
            c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
        ).casefold()
        if s
        else None,
    )
    return conn
