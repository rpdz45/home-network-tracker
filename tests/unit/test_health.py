"""Tests for collector health and the one-event-per-outage rule (injected clock, no sleep)."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.db.health import collector_health, record_stale_event
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository, ScanStatus

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
LIMIT = 600
STALE_EVENTS_SQL = "SELECT COUNT(*) FROM events WHERE kind = 'collector_stale'"
NOTIFICATIONS_SQL = "SELECT COUNT(*) FROM notifications"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrate(connection)
    yield connection
    connection.close()


def _scan(
    conn: sqlite3.Connection, at: datetime, status: ScanStatus = "ok", error: str | None = None
) -> None:
    repo = Repository(conn)
    scan_id = repo.start_scan(mode="passive", started_at=at)
    repo.finish_scan(scan_id, status=status, finished_at=at + timedelta(seconds=1), error=error)


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def test_no_scan_is_not_reported_stale(conn: sqlite3.Connection) -> None:
    health = collector_health(conn, T0, LIMIT)
    assert health.last_success_at is None
    assert health.age_seconds is None
    assert not health.stale
    assert not record_stale_event(conn, T0 + timedelta(days=1), LIMIT)
    assert _count(conn, STALE_EVENTS_SQL) == 0


def test_recent_success_is_healthy(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    health = collector_health(conn, T0 + timedelta(minutes=5), LIMIT)
    assert not health.stale
    assert health.age_seconds == 299.0
    assert health.recent_problems == ()


def test_threshold_is_strict(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    at_limit = T0 + timedelta(seconds=1 + LIMIT)
    assert not collector_health(conn, at_limit, LIMIT).stale
    assert collector_health(conn, at_limit + timedelta(seconds=1), LIMIT).stale


def test_stale_event_is_created_once_per_outage(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    assert record_stale_event(conn, T0 + timedelta(minutes=11), LIMIT)
    assert not record_stale_event(conn, T0 + timedelta(minutes=12), LIMIT)
    assert not record_stale_event(conn, T0 + timedelta(hours=3), LIMIT)
    assert _count(conn, STALE_EVENTS_SQL) == 1
    event = Repository(conn).list_events(kind="collector_stale")[0]
    assert event.details is not None
    assert event.details["stale_after_seconds"] == LIMIT
    assert event.details["age_seconds"] == 659


def test_successful_scan_rearms_the_alert(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    assert record_stale_event(conn, T0 + timedelta(minutes=11), LIMIT)
    _scan(conn, T0 + timedelta(minutes=20))
    assert not record_stale_event(conn, T0 + timedelta(minutes=25), LIMIT)
    assert record_stale_event(conn, T0 + timedelta(minutes=31), LIMIT)
    assert _count(conn, STALE_EVENTS_SQL) == 2


def test_failed_scan_does_not_count_as_success(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    _scan(conn, T0 + timedelta(minutes=9), status="error", error="OSError")
    health = collector_health(conn, T0 + timedelta(minutes=11), LIMIT)
    assert health.stale
    assert health.last_success_at is not None
    assert health.last_success_at.startswith("2026-10-23T12:00:01")
    assert [problem.error for problem in health.recent_problems] == ["OSError"]


def test_reading_health_never_writes(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    assert collector_health(conn, T0 + timedelta(hours=1), LIMIT).stale
    assert _count(conn, STALE_EVENTS_SQL) == 0


def test_recording_never_creates_a_notification(conn: sqlite3.Connection) -> None:
    _scan(conn, T0)
    assert record_stale_event(conn, T0 + timedelta(hours=1), LIMIT)
    assert _count(conn, NOTIFICATIONS_SQL) == 0


def test_problem_list_is_bounded(conn: sqlite3.Connection) -> None:
    for minute in range(8):
        _scan(conn, T0 + timedelta(minutes=minute), status="error", error="OSError")
    health = collector_health(conn, T0 + timedelta(minutes=9), LIMIT, problem_limit=3)
    assert len(health.recent_problems) == 3


def test_invalid_arguments_are_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="positive"):
        collector_health(conn, T0, 0)
    with pytest.raises(ValueError, match="problem_limit"):
        collector_health(conn, T0, LIMIT, problem_limit=0)
    with pytest.raises(ValueError, match="timezone"):
        collector_health(conn, datetime(2026, 10, 23, 12, 0), LIMIT)
