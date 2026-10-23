"""Collector health: last successful scan, recent problems and one stale event per outage.

Reads the ``scans`` table written by every discovery cycle. Nothing here touches the network
and nothing is ever sent: the stale event is only recorded locally.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nettracker.db.repository import Repository, to_iso
from nettracker.errors import DatabaseError

PROBLEM_LIMIT = 5

_LAST_SUCCESS_SQL = "SELECT MAX(finished_at) FROM scans WHERE status = 'ok'"
_LAST_STALE_EVENT_SQL = "SELECT MAX(created_at) FROM events WHERE kind = 'collector_stale'"
_PROBLEMS_SQL = (
    "SELECT started_at, finished_at, status, error FROM scans "
    "WHERE status != 'ok' ORDER BY id DESC LIMIT ?"
)


@dataclass(frozen=True)
class ScanProblem:
    """A scan that did not succeed (``finished_at`` is empty if it never finished)."""

    started_at: str
    finished_at: str | None
    status: str
    error: str | None


@dataclass(frozen=True)
class CollectorHealth:
    last_success_at: str | None
    age_seconds: float | None
    stale: bool
    recent_problems: tuple[ScanProblem, ...]


def _query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot read collector health: {exc}") from exc


def collector_health(
    conn: sqlite3.Connection,
    now: datetime,
    stale_after_seconds: float,
    *,
    problem_limit: int = PROBLEM_LIMIT,
) -> CollectorHealth:
    """Read-only summary. A collector with no successful scan yet is not reported as stale."""
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")
    if problem_limit < 1:
        raise ValueError("problem_limit must be at least 1")
    to_iso(now)
    last_success: str | None = _query(conn, _LAST_SUCCESS_SQL)[0][0]
    age: float | None = None
    if last_success is not None:
        age = (now - datetime.fromisoformat(last_success)).total_seconds()
    problems = tuple(
        ScanProblem(row[0], row[1], row[2], row[3])
        for row in _query(conn, _PROBLEMS_SQL, (problem_limit,))
    )
    stale = age is not None and age > stale_after_seconds
    return CollectorHealth(last_success, age, stale, problems)


def record_stale_event(
    conn: sqlite3.Connection,
    now: datetime,
    stale_after_seconds: float,
) -> bool:
    """Record ``collector_stale`` once per outage; return True only if an event was created.

    The next successful scan re-arms the rule: while the latest ``collector_stale`` event is
    newer than the latest successful scan, no further event is created.
    """
    repo = Repository(conn)
    with repo.transaction():
        health = collector_health(conn, now, stale_after_seconds)
        if not health.stale or health.last_success_at is None or health.age_seconds is None:
            return False
        last_event: str | None = _query(conn, _LAST_STALE_EVENT_SQL)[0][0]
        if last_event is not None and last_event >= health.last_success_at:
            return False
        repo.add_event(
            "collector_stale",
            created_at=now,
            details={
                "last_success_at": health.last_success_at,
                "age_seconds": round(health.age_seconds),
                "stale_after_seconds": stale_after_seconds,
            },
        )
    return True
