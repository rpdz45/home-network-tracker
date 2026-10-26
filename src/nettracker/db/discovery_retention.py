"""Opt-in pruning of superseded discovery observations and unused old scans."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nettracker.errors import ConfigError, DatabaseError

_OBSERVATIONS = (
    "SELECT s.id FROM sightings s WHERE s.source = 'discovery' AND s.seen_at < :cutoff "
    "AND s.id != (SELECT t.id FROM sightings t WHERE t.device_id = s.device_id "
    "AND t.source = 'discovery' ORDER BY t.seen_at DESC, t.id DESC LIMIT 1) "
    "ORDER BY s.id LIMIT :limit"
)
_SCANS = (
    "SELECT s.id FROM scans s WHERE s.started_at < :cutoff AND s.finished_at < :cutoff "
    "AND NOT EXISTS (SELECT 1 FROM sightings o WHERE o.scan_id = s.id) "
    "AND s.id NOT IN (SELECT id FROM scans WHERE status = 'ok' AND finished_at IS NOT NULL "
    "ORDER BY finished_at DESC, id DESC LIMIT 1) "
    "AND s.id NOT IN (SELECT id FROM scans WHERE status != 'ok' ORDER BY id DESC LIMIT 5) "
    "ORDER BY s.id LIMIT :limit"
)


@dataclass(frozen=True)
class DiscoveryRetentionResult:
    observations: int
    scans: int
    applied: bool


def _prune(
    conn: sqlite3.Connection,
    query: str,
    deletion: str,
    cutoff: str,
    batch_size: int,
    max_batches: int,
) -> int:
    deleted = 0
    for _ in range(max_batches):
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(query, {"cutoff": cutoff, "limit": batch_size}).fetchall()
            batch = conn.executemany(deletion, rows).rowcount if rows else 0
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        deleted += batch
        if batch < batch_size:
            break
    return deleted


def retain_discovery(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    keep_days: int = 30,
    batch_size: int = 500,
    max_batches: int = 100,
    enabled: bool = False,
) -> DiscoveryRetentionResult:
    """Preview by default; apply bounded batches only when explicitly enabled.

    Preview scan counts describe the current state, before any observation removal.
    The latest discovery per device, latest success and five latest problems survive.
    """
    for value, maximum in ((keep_days, 3650), (batch_size, 5000), (max_batches, 1000)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ConfigError("invalid discovery retention limits")
    if not isinstance(enabled, bool):
        raise ConfigError("discovery retention activation must be boolean")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ConfigError("discovery retention requires a timezone-aware clock")
    if conn.in_transaction:
        raise ConfigError("discovery retention cannot join an existing transaction")
    try:
        moment = now - timedelta(days=keep_days)
        cutoff = moment.astimezone(UTC).isoformat(timespec="microseconds")
    except OverflowError as exc:
        raise ConfigError("discovery retention cutoff is outside the datetime range") from exc
    try:
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ConfigError("discovery retention requires foreign_keys=ON")
        if not enabled:
            params = {"cutoff": cutoff, "limit": -1}
            observations = sum(1 for _ in conn.execute(_OBSERVATIONS, params))
            scans = sum(1 for _ in conn.execute(_SCANS, params))
            return DiscoveryRetentionResult(observations, scans, applied=False)
        observations = _prune(
            conn,
            _OBSERVATIONS,
            "DELETE FROM sightings WHERE id = ?",
            cutoff,
            batch_size,
            max_batches,
        )
        scans = _prune(
            conn,
            _SCANS,
            "DELETE FROM scans WHERE id = ?",
            cutoff,
            batch_size,
            max_batches,
        )
        return DiscoveryRetentionResult(observations, scans, applied=True)
    except sqlite3.Error as exc:
        raise DatabaseError("discovery retention database operation failed") from exc
