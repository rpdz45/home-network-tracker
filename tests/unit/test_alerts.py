"""Tests for alert dispatch: dry-run default, anti-spam and failure isolation."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest

from nettracker.alerts.engine import AlertMessage, NotifierError, process_pending_events
from nettracker.alerts.rules import NOTIFIABLE_KINDS
from nettracker.config import AlertSettings
from nettracker.db.migrations import migrate
from nettracker.db.repository import EventKind, Repository
from nettracker.errors import ConfigError

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=2)
ROWS_SQL = "SELECT event_id, channel, status FROM notifications ORDER BY id"
ERRORS_SQL = "SELECT error FROM notifications ORDER BY id"
PROCESSED_KINDS_SQL = "SELECT e.kind FROM events e JOIN notifications n ON n.event_id = e.id"
LIVE = AlertSettings(dry_run=False)


class Recorder:
    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.messages: list[AlertMessage] = []

    def send(self, message: AlertMessage) -> None:
        self.messages.append(message)


class Broken:
    name = "broken"

    def send(self, message: AlertMessage) -> None:
        raise NotifierError("secret-token-in-message")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrate(connection)
    yield connection
    connection.close()


def _device(repo: Repository, index: int = 1) -> int:
    mac = f"aa:bb:cc:dd:ee:{index:02x}"
    return repo.upsert_device(mac, seen_at=T0, hostname=f"host{index}").id


def _rows(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    return [(row[0], row[1], row[2]) for row in conn.execute(ROWS_SQL).fetchall()]


def test_dry_run_records_without_sending(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("new_device", created_at=T0, device_id=_device(repo))
    recorder = Recorder()
    summary = process_pending_events(conn, AlertSettings(), NOW, [recorder])
    assert (summary.processed, summary.dry_run, summary.sent) == (1, 1, 0)
    assert recorder.messages == []
    assert _rows(conn) == [(1, "dry-run", "dry_run")]


def test_only_notifiable_kinds_are_processed(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    for kind in get_args(EventKind):
        repo.add_event(kind, created_at=T0)
    summary = process_pending_events(conn, AlertSettings(), NOW)
    processed = {row[0] for row in conn.execute(PROCESSED_KINDS_SQL).fetchall()}
    assert processed == set(NOTIFIABLE_KINDS)
    assert summary.processed == len(NOTIFIABLE_KINDS)
    assert "to_confirm" not in processed
    assert "online" not in processed


def test_events_are_processed_only_once(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("collector_stale", created_at=T0)
    assert process_pending_events(conn, AlertSettings(), NOW).processed == 1
    assert process_pending_events(conn, AlertSettings(), NOW).processed == 0
    assert len(_rows(conn)) == 1


def test_cooldown_suppresses_repeats_per_device_and_kind(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    first, second = _device(repo, 1), _device(repo, 2)
    repo.add_event("offline", created_at=T0, device_id=first)
    repo.add_event("offline", created_at=T0 + timedelta(minutes=10), device_id=first)
    repo.add_event("offline", created_at=T0 + timedelta(minutes=10), device_id=second)
    repo.add_event("offline", created_at=T0 + timedelta(minutes=31), device_id=first)
    summary = process_pending_events(conn, AlertSettings(cooldown_minutes=30), NOW)
    statuses = [status for _, _, status in _rows(conn)]
    assert statuses == ["dry_run", "suppressed", "dry_run", "dry_run"]
    assert (summary.dry_run, summary.suppressed) == (3, 1)


def test_other_kinds_for_the_same_device_are_not_suppressed(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    repo.add_event("new_device", created_at=T0, device_id=device)
    repo.add_event("offline", created_at=T0, device_id=device)
    summary = process_pending_events(conn, AlertSettings(), NOW)
    assert (summary.dry_run, summary.suppressed) == (2, 0)


def test_live_mode_sends_a_readable_message(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("new_device", created_at=T0, device_id=_device(repo))
    recorder = Recorder()
    summary = process_pending_events(conn, LIVE, NOW, [recorder])
    assert (summary.sent, summary.failed) == (1, 0)
    message = recorder.messages[0]
    assert (message.event_id, message.kind, message.severity) == (1, "new_device", "critical")
    assert "host1" in message.text
    assert "aa:bb:cc:dd:ee:01" in message.text
    assert _rows(conn) == [(1, "fake", "sent")]


def test_collector_stale_message_uses_the_event_details(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    stamp = "2026-10-23T11:00:00+00:00"
    repo.add_event("collector_stale", created_at=T0, details={"last_success_at": stamp})
    recorder = Recorder()
    process_pending_events(conn, LIVE, NOW, [recorder])
    assert stamp in recorder.messages[0].text


def test_failed_notifier_is_recorded_without_its_message(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("new_device", created_at=T0, device_id=_device(repo))
    recorder = Recorder()
    summary = process_pending_events(conn, LIVE, NOW, [Broken(), recorder])
    assert (summary.sent, summary.failed) == (1, 1)
    assert _rows(conn) == [(1, "broken", "failed"), (1, "fake", "sent")]
    errors = [row[0] for row in conn.execute(ERRORS_SQL).fetchall()]
    assert errors == ["NotifierError", None]


def test_failed_delivery_does_not_start_a_cooldown(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    repo.add_event("offline", created_at=T0, device_id=device)
    process_pending_events(conn, LIVE, NOW, [Broken()])
    repo.add_event("offline", created_at=T0 + timedelta(minutes=5), device_id=device)
    summary = process_pending_events(conn, LIVE, NOW, [Recorder()])
    assert (summary.sent, summary.suppressed) == (1, 0)


def test_live_mode_requires_a_notifier(conn: sqlite3.Connection) -> None:
    Repository(conn).add_event("new_device", created_at=T0)
    with pytest.raises(ConfigError, match="notifier"):
        process_pending_events(conn, LIVE, NOW)
    assert _rows(conn) == []


def test_each_run_is_bounded(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    for index in range(1, 4):
        repo.add_event("new_device", created_at=T0, device_id=_device(repo, index))
    settings = AlertSettings(max_events_per_run=2)
    assert process_pending_events(conn, settings, NOW).processed == 2
    assert process_pending_events(conn, settings, NOW).processed == 1
    assert process_pending_events(conn, settings, NOW).processed == 0


def test_naive_clock_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="timezone"):
        process_pending_events(conn, AlertSettings(), datetime(2026, 10, 23, 12, 0))
