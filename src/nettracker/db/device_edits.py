"""Validated device edits; callers must enforce authentication and CSRF protection."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from nettracker.errors import DatabaseError

DEVICE_TYPES = frozenset({"computer", "phone", "network", "iot", "tv", "nas", "camera", "other"})
MAX_ALIAS_LENGTH = 120


def _alias(value: str) -> str | None:
    cleaned = value.strip()
    if len(cleaned) > MAX_ALIAS_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise ValueError("alias must contain at most 120 characters and no control characters")
    return cleaned or None


@contextmanager
def _edit(conn: sqlite3.Connection, device_id: int) -> Iterator[str]:
    if isinstance(device_id, bool) or device_id <= 0:
        raise ValueError("device_id must be positive")
    started = False
    try:
        conn.execute("SAVEPOINT device_edit")
        started = True
        row = conn.execute(
            "SELECT status, merged_into FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        if row is None:
            raise LookupError("device not found")
        if row[1] is not None:
            raise ValueError("merged devices cannot be edited")
        yield str(row[0])
        conn.execute("RELEASE SAVEPOINT device_edit")
        started = False
    except BaseException as exc:
        if started:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT device_edit")
                conn.execute("RELEASE SAVEPOINT device_edit")
            except sqlite3.Error as rollback_error:
                raise DatabaseError("cannot roll back device edit") from rollback_error
        if isinstance(exc, sqlite3.Error):
            raise DatabaseError("cannot update device") from exc
        raise


def update_identity(
    conn: sqlite3.Connection, device_id: int, *, alias: str, device_type: str
) -> None:
    """Replace the alias and type atomically; blank values clear the corresponding field."""
    normalized_alias = _alias(alias)
    normalized_type = device_type.strip() or None
    if normalized_type is not None and normalized_type not in DEVICE_TYPES:
        raise ValueError("unsupported device type")
    with _edit(conn, device_id):
        conn.execute(
            "UPDATE devices SET alias = ?, device_type = ? WHERE id = ?",
            (normalized_alias, normalized_type, device_id),
        )


def mark_known(conn: sqlite3.Connection, device_id: int) -> None:
    """Persist owner approval without changing ignored/merged devices or historical events."""
    with _edit(conn, device_id) as status:
        if status == "ignored":
            raise ValueError("ignored devices require an explicit reclassification")
        conn.execute("UPDATE devices SET status = 'known' WHERE id = ?", (device_id,))
