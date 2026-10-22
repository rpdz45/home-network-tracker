"""Bounded pruning of old ping samples.

Only rows with ``source = 'ping'`` are ever deleted. Devices, discovery observations,
monitor state, events and notifications are never touched.
"""

import sqlite3
from datetime import datetime, timedelta

from nettracker.db.repository import to_iso
from nettracker.errors import DatabaseError


def cutoff_for(now: datetime, keep_days: int) -> str:
    """Return the ISO cutoff: ping samples strictly older than this are prunable."""
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    return to_iso(now - timedelta(days=keep_days))


def count_prunable(conn: sqlite3.Connection, cutoff: str) -> int:
    """Preview only: count prunable ping samples without modifying anything."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sightings WHERE source = 'ping' AND seen_at < ?",
            (cutoff,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot count prunable samples: {exc}") from exc
    return int(row[0])


def prune_ping_samples(
    conn: sqlite3.Connection,
    cutoff: str,
    *,
    batch_size: int = 500,
    max_batches: int = 100,
) -> int:
    """Delete old ping samples in bounded batches, one transaction per batch."""
    if batch_size < 1 or max_batches < 1:
        raise ValueError("batch_size and max_batches must be at least 1")
    deleted = 0
    for _ in range(max_batches):
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "DELETE FROM sightings WHERE id IN ("
                "SELECT id FROM sightings WHERE source = 'ping' AND seen_at < ? "
                "ORDER BY id LIMIT ?)",
                (cutoff, batch_size),
            )
            batch = cursor.rowcount
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise DatabaseError(f"pruning failed: {exc}") from exc
        deleted += batch
        if batch < batch_size:
            break
    return deleted
