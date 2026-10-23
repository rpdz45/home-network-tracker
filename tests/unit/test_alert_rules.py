"""Tests for the offline delay, recovery suppression and sustained-latency detection."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.alerts.engine import AlertMessage, process_pending_events
from nettracker.alerts.latency import detect_high_latency
from nettracker.config import AlertSettings
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository, to_iso

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
ROWS_SQL = "SELECT event_id, channel, status FROM notifications ORDER BY id"
ERRORS_SQL = "SELECT error FROM notifications ORDER BY id"
LATENCY_EVENTS_SQL = "SELECT COUNT(*) FROM events WHERE kind = 'latency_high'"
SAMPLE_SQL = (
    "INSERT INTO sightings "
    "(device_id, ip, online, latency_ms, packet_loss_pct, seen_at, source) "
    "VALUES (?, '192.168.1.10', ?, ?, ?, ?, 'ping')"
)
THRESHOLD = 200


class Recorder:
    def __init__(self) -> None:
        self.name = "fake"
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


def _device(repo: Repository, index: int = 1) -> int:
    mac = f"aa:bb:cc:dd:ee:{index:02x}"
    return repo.upsert_device(mac, seen_at=T0, hostname=f"host{index}").id


def _sample(conn: sqlite3.Connection, device_id: int, minute: int, latency: float | None) -> None:
    online = latency is not None
    loss = 0.0 if online else 100.0
    stamp = to_iso(T0 + timedelta(minutes=minute))
    conn.execute(SAMPLE_SQL, (device_id, int(online), latency, loss, stamp))


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _at(minute: int) -> datetime:
    return T0 + timedelta(minutes=minute)


def test_offline_alert_waits_for_the_delay(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("offline", created_at=T0, device_id=_device(repo))
    settings = AlertSettings(offline_after_minutes=5)
    assert process_pending_events(conn, settings, _at(4)).processed == 0
    assert conn.execute(ROWS_SQL).fetchall() == []
    due = process_pending_events(conn, settings, _at(5))
    assert (due.processed, due.dry_run) == (1, 1)


def test_zero_delay_alerts_immediately(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("offline", created_at=T0, device_id=_device(repo))
    summary = process_pending_events(conn, AlertSettings(offline_after_minutes=0), T0)
    assert (summary.processed, summary.dry_run) == (1, 1)


def test_the_delay_applies_only_to_offline_events(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    repo.add_event("new_device", created_at=T0, device_id=_device(repo))
    summary = process_pending_events(conn, AlertSettings(offline_after_minutes=5), T0)
    assert (summary.processed, summary.dry_run) == (1, 1)


def test_offline_alert_is_dropped_when_the_device_came_back(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    repo.add_event("offline", created_at=T0, device_id=device)
    repo.add_event("online", created_at=_at(2), device_id=device)
    summary = process_pending_events(conn, AlertSettings(), _at(10))
    assert (summary.processed, summary.suppressed, summary.dry_run) == (1, 1, 0)
    assert [row[0] for row in conn.execute(ERRORS_SQL)] == ["recovered"]


def test_an_earlier_online_event_does_not_cancel_the_alert(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    repo.add_event("online", created_at=T0, device_id=device)
    repo.add_event("offline", created_at=_at(1), device_id=device)
    summary = process_pending_events(conn, AlertSettings(), _at(10))
    assert (summary.suppressed, summary.dry_run) == (0, 1)


def test_another_device_coming_back_does_not_cancel_the_alert(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    first, second = _device(repo, 1), _device(repo, 2)
    repo.add_event("offline", created_at=T0, device_id=first)
    repo.add_event("online", created_at=_at(2), device_id=second)
    summary = process_pending_events(conn, AlertSettings(), _at(10))
    assert (summary.suppressed, summary.dry_run) == (0, 1)


def test_sustained_latency_creates_one_event_per_episode(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 300.0)
    assert detect_high_latency(conn, _at(3), THRESHOLD) == 1
    assert detect_high_latency(conn, _at(4), THRESHOLD) == 0
    assert _count(conn, LATENCY_EVENTS_SQL) == 1
    event = repo.list_events(kind="latency_high")[0]
    assert event.device_id == device
    assert event.details == {"average_ms": 300.0, "samples": 3, "threshold_ms": THRESHOLD}


def test_the_same_episode_does_not_repeat(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 300.0)
    assert detect_high_latency(conn, _at(3), THRESHOLD) == 1
    for minute in range(4, 7):
        _sample(conn, device, minute, 300.0)
    assert detect_high_latency(conn, _at(7), THRESHOLD) == 0


def test_a_normal_sample_starts_a_new_episode(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 300.0)
    assert detect_high_latency(conn, _at(3), THRESHOLD) == 1
    _sample(conn, device, 4, 10.0)
    for minute in range(5, 8):
        _sample(conn, device, minute, 300.0)
    assert detect_high_latency(conn, _at(8), THRESHOLD) == 1
    assert _count(conn, LATENCY_EVENTS_SQL) == 2


def test_not_enough_samples_is_not_an_alert(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(2):
        _sample(conn, device, minute, 900.0)
    assert detect_high_latency(conn, _at(3), THRESHOLD) == 0


def test_the_mean_must_be_strictly_above_the_threshold(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute, latency in enumerate((100.0, 100.0, 400.0)):
        _sample(conn, device, minute, latency)
    assert detect_high_latency(conn, _at(3), THRESHOLD) == 0
    _sample(conn, device, 3, 400.0)
    assert detect_high_latency(conn, _at(4), THRESHOLD) == 1


def test_unanswered_probes_are_ignored(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute, latency in enumerate((300.0, None, 300.0, None, 300.0)):
        _sample(conn, device, minute, latency)
    assert detect_high_latency(conn, _at(5), THRESHOLD) == 1


def test_only_unanswered_probes_is_not_a_latency_alert(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(5):
        _sample(conn, device, minute, None)
    assert detect_high_latency(conn, _at(5), THRESHOLD) == 0


def test_old_samples_are_ignored(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 900.0)
    assert detect_high_latency(conn, _at(180), THRESHOLD) == 0


def test_invalid_threshold_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="positive"):
        detect_high_latency(conn, T0, 0)


def test_process_alerts_detects_then_dispatches_once(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 300.0)
    settings = AlertSettings(latency_high_ms=THRESHOLD)
    first = process_pending_events(conn, settings, _at(3))
    assert (first.latency_events, first.processed, first.dry_run) == (1, 1, 1)
    second = process_pending_events(conn, settings, _at(4))
    assert (second.latency_events, second.processed) == (0, 0)


def test_latency_message_mentions_the_average(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)
    device = _device(repo)
    for minute in range(3):
        _sample(conn, device, minute, 300.0)
    recorder = Recorder()
    process_pending_events(conn, AlertSettings(dry_run=False), _at(3), [recorder])
    assert "300.0 ms" in recorder.messages[0].text
    assert recorder.messages[0].kind == "latency_high"
