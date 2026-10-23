"""Detect sustained high latency from stored ping samples.

Reads the ``sightings`` rows written by ``monitor-once`` and writes at most one
``latency_high`` event per device and episode. No network access.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from nettracker.db.repository import Repository, to_iso
from nettracker.errors import DatabaseError

SAMPLES = 3
RECENT_MINUTES = 60

_DEVICES_SQL = "SELECT DISTINCT device_id FROM sightings WHERE source = 'ping' AND seen_at >= ?"
_LATEST_SQL = (
    "SELECT latency_ms, seen_at FROM sightings "
    "WHERE device_id = ? AND source = 'ping' AND latency_ms IS NOT NULL "
    "ORDER BY seen_at DESC, id DESC LIMIT ?"
)
_LAST_EVENT_SQL = "SELECT MAX(created_at) FROM events WHERE kind = 'latency_high' AND device_id = ?"
_NORMAL_SINCE_SQL = (
    "SELECT 1 FROM sightings WHERE device_id = ? AND source = 'ping' "
    "AND latency_ms <= ? AND seen_at > ? LIMIT 1"
)


def _query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot read latency samples: {exc}") from exc


def _in_current_episode(conn: sqlite3.Connection, device_id: int, threshold_ms: float) -> bool:
    """True while no normal sample has been seen since the last ``latency_high`` event."""
    last_event = _query(conn, _LAST_EVENT_SQL, (device_id,))[0][0]
    if last_event is None:
        return False
    return not _query(conn, _NORMAL_SINCE_SQL, (device_id, threshold_ms, last_event))


def detect_high_latency(conn: sqlite3.Connection, now: datetime, threshold_ms: float) -> int:
    """Create at most one ``latency_high`` event per device and episode; return how many.

    A device qualifies when the mean of its last answered pings (``SAMPLES``) is strictly above
    the threshold and the newest sample is recent. A sample at or below the threshold ends the
    episode, so a later sustained spike raises a new event.
    """
    if threshold_ms <= 0:
        raise ValueError("threshold_ms must be positive")
    cutoff = to_iso(now - timedelta(minutes=RECENT_MINUTES))
    repo = Repository(conn)
    created = 0
    for device_row in _query(conn, _DEVICES_SQL, (cutoff,)):
        device_id = device_row[0]
        with repo.transaction():
            samples = _query(conn, _LATEST_SQL, (device_id, SAMPLES))
            if len(samples) < SAMPLES or samples[0][1] < cutoff:
                continue
            average = sum(row[0] for row in samples) / SAMPLES
            if average <= threshold_ms or _in_current_episode(conn, device_id, threshold_ms):
                continue
            repo.add_event(
                "latency_high",
                created_at=now,
                device_id=device_id,
                details={
                    "average_ms": round(average, 1),
                    "samples": SAMPLES,
                    "threshold_ms": threshold_ms,
                },
            )
            created += 1
    return created
