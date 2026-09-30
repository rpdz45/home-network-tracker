"""SQLite connection helper."""

import sqlite3
from pathlib import Path

from nettracker.errors import DatabaseError

BUSY_TIMEOUT_SECONDS = 5.0


def connect(path: Path | str, *, timeout: float = BUSY_TIMEOUT_SECONDS) -> sqlite3.Connection:
    """Open a connection in autocommit mode with foreign keys and WAL enabled.

    Transactions are managed explicitly by the repository.
    """
    try:
        conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot open database {path}: {exc}") from exc
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        conn.close()
        raise DatabaseError(f"cannot use database {path}: {exc}") from exc
    return conn
