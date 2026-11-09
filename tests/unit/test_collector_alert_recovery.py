"""Collector recovery suppression with SQLite and in-memory notifiers only."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.alerts.engine import AlertMessage, process_pending_events
from nettracker.config import AlertSettings
from nettracker.db.health import record_stale_event
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository, ScanStatus

T0 = datetime(2026, 11, 9, 12, tzinfo=UTC)
NOW = T0 + timedelta(hours=2)


class Recorder:
    name = "synthetic"

    def __init__(self) -> None:
        self.messages: list[AlertMessage] = []

    def send(self, message: AlertMessage) -> None:
        self.messages.append(message)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrate(connection)
    yield connection
    connection.close()


def scan(
    conn: sqlite3.Connection,
    finished_at: datetime,
    *,
    status: ScanStatus = "ok",
    finished: bool = True,
    started_at: datetime | None = None,
) -> None:
    repo = Repository(conn)
    scan_id = repo.start_scan(
        mode="passive", started_at=started_at or finished_at - timedelta(seconds=1)
    )
    if finished:
        repo.finish_scan(scan_id, status=status, finished_at=finished_at)


def notifications(conn: sqlite3.Connection) -> list[tuple[int, str, str, str | None]]:
    return [
        (row[0], row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT event_id, channel, status, error FROM notifications ORDER BY id"
        )
    ]


@pytest.mark.parametrize("dry_run", [True, False])
def test_recovered_collector_does_not_notify(conn: sqlite3.Connection, dry_run: bool) -> None:
    event = Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1))
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=dry_run), NOW, [recorder])
    assert (summary.processed, summary.suppressed, summary.sent, summary.dry_run) == (1, 1, 0, 0)
    assert recorder.messages == []
    assert notifications(conn) == [(event, "all", "suppressed", "recovered")]


@pytest.mark.parametrize("offset", [-1, 0, 121])
def test_older_equal_or_future_success_does_not_cancel(
    conn: sqlite3.Connection, offset: int
) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=offset))
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=False), NOW, [recorder])
    assert (summary.sent, summary.suppressed) == (1, 0)
    assert len(recorder.messages) == 1


@pytest.mark.parametrize(("status", "finished"), [("error", True), ("denied", True), ("ok", False)])
def test_unsuccessful_or_unfinished_scan_is_not_recovery(
    conn: sqlite3.Connection, status: ScanStatus, finished: bool
) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1), status=status, finished=finished)
    summary = process_pending_events(conn, AlertSettings(), NOW)
    assert (summary.dry_run, summary.suppressed) == (1, 0)


def test_no_success_keeps_the_alert(conn: sqlite3.Connection) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    summary = process_pending_events(conn, AlertSettings(), NOW)
    assert (summary.dry_run, summary.suppressed) == (1, 0)


@pytest.mark.parametrize("finished_at", [T0 + timedelta(microseconds=1), NOW])
def test_strict_recovery_boundary_and_current_instant(
    conn: sqlite3.Connection, finished_at: datetime
) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, finished_at)
    summary = process_pending_events(conn, AlertSettings(), NOW)
    assert (summary.suppressed, summary.dry_run) == (1, 0)


def test_completion_time_matters_not_scan_start(conn: sqlite3.Connection) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1), started_at=T0 - timedelta(minutes=1))
    assert process_pending_events(conn, AlertSettings(), NOW).suppressed == 1


def test_suppression_is_persistent_and_does_not_delete_history(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    event = repo.add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1))
    summary = process_pending_events(conn, AlertSettings(), NOW)
    assert summary.suppressed == 1
    assert process_pending_events(conn, AlertSettings(), NOW).processed == 0
    assert [(item.id, item.kind) for item in repo.list_events()] == [(event, "collector_stale")]
    assert len(notifications(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1


def test_recovered_event_does_not_cool_down_new_outage(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    first = repo.add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1))
    second = repo.add_event("collector_stale", created_at=T0 + timedelta(minutes=2))
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=False), NOW, [recorder])
    assert (summary.suppressed, summary.sent) == (1, 1)
    assert [message.event_id for message in recorder.messages] == [second]
    assert notifications(conn) == [
        (first, "all", "suppressed", "recovered"),
        (second, "synthetic", "sent", None),
    ]


def test_full_health_cycle_rearms_and_sends_only_current_outage(conn: sqlite3.Connection) -> None:
    scan(conn, T0 - timedelta(minutes=20))
    assert record_stale_event(conn, T0, 600)
    scan(conn, T0 + timedelta(minutes=1))
    second_outage = T0 + timedelta(minutes=12)
    assert record_stale_event(conn, second_outage, 600)
    assert not record_stale_event(conn, second_outage + timedelta(seconds=1), 600)
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=False), second_outage, [recorder])
    assert (summary.processed, summary.suppressed, summary.sent) == (2, 1, 1)
    assert len(recorder.messages) == 1
    assert recorder.messages[0].event_id == notifications(conn)[1][0]


def test_multiple_notifiers_are_all_skipped(conn: sqlite3.Connection) -> None:
    Repository(conn).add_event("collector_stale", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1))
    first, second = Recorder(), Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=False), NOW, [first, second])
    assert summary.suppressed == 1
    assert first.messages == second.messages == []
    assert len(notifications(conn)) == 1


def test_recovery_does_not_cancel_other_event_kinds(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    stale = repo.add_event("collector_stale", created_at=T0)
    other = repo.add_event("new_device", created_at=T0)
    scan(conn, T0 + timedelta(minutes=1))
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(dry_run=False), NOW, [recorder])
    assert (summary.suppressed, summary.sent) == (1, 1)
    assert [message.event_id for message in recorder.messages] == [other]
    assert notifications(conn)[0] == (stale, "all", "suppressed", "recovered")


def test_run_limit_still_applies_to_recovered_events(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    for index in range(3):
        repo.add_event("collector_stale", created_at=T0 + timedelta(seconds=index))
    scan(conn, T0 + timedelta(minutes=1))
    settings = AlertSettings(max_events_per_run=2)
    first = process_pending_events(conn, settings, NOW)
    second = process_pending_events(conn, settings, NOW)
    assert (first.processed, first.suppressed) == (2, 2)
    assert (second.processed, second.suppressed) == (1, 1)
    assert process_pending_events(conn, settings, NOW).processed == 0
