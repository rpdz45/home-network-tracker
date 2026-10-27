"""Opt-in ping retention in the CLI loop; disposable SQLite and injected I/O only."""

import signal
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.repository import to_iso
from nettracker.db.retention import cutoff_for, prune_ping_samples
from nettracker.errors import ConfigError, DatabaseError
from nettracker.monitor import loop
from nettracker.monitor.ping import PingError, PingResult
from nettracker.monitor.service import monitor_once

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
ARGS = ["--device-id", "1", "--enable-monitoring"]


@dataclass
class Case:
    conn: sqlite3.Connection
    settings: Settings
    probes: Mock

    def expired(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM sightings WHERE source='ping' AND seen_at < ?",
            (cutoff_for(NOW, 1),),
        ).fetchone()
        return int(row[0])


def protected(conn: sqlite3.Connection) -> list[list[tuple[object, ...]]]:
    queries = [
        "SELECT * FROM devices ORDER BY id",
        "SELECT * FROM sightings WHERE source='discovery' ORDER BY id",
        "SELECT * FROM scans ORDER BY id",
        "SELECT * FROM monitor_state ORDER BY device_id",
        "SELECT * FROM events ORDER BY id",
        "SELECT * FROM notifications ORDER BY id",
    ]
    return [[tuple(row) for row in conn.execute(query)] for query in queries]


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Case]:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real cache, ping and user configuration are forbidden")

    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    path = tmp_path / "retention.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        for index in (1, 2):
            device = repo.upsert_device(f"02:00:00:00:00:{index:02x}", seen_at=NOW)
            repo.add_sighting(
                device_id=device.id, ip=f"192.168.1.{index + 19}", online=True, seen_at=NOW
            )
        for index in range(7):
            moment = NOW - timedelta(days=2) if index < 5 else NOW - timedelta(days=1)
            if index == 6:
                moment = NOW - timedelta(hours=1)
            device_id = 1 if index % 2 == 0 else 2
            conn.execute(
                "INSERT INTO sightings (device_id, ip, online, latency_ms, packet_loss_pct, "
                "seen_at, source) VALUES (?, ?, 1, 1.0, 0.0, ?, 'ping')",
                (device_id, f"192.168.1.{device_id + 19}", to_iso(moment)),
            )
        event = repo.add_event("new_device", device_id=1, created_at=NOW)
        repo.add_notification(event_id=event, channel="fixture", status="dry_run", sent_at=NOW)
        settings = Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "database_path": str(path),
                "monitor": {"enabled": True},
                "retention": {"enabled": True, "keep_days": 1, "batch_size": 2, "max_batches": 9},
            }
        )
        probes = Mock(return_value=PingResult(1, 1, 1.0))
        ticks = 0

        def injected(
            repository: MonitoringRepository,
            configured: Settings,
            device_ids: Sequence[int],
            *,
            enabled: bool = False,
        ) -> int:
            nonlocal ticks
            moment = NOW + timedelta(seconds=ticks)
            ticks += 1
            assert not conn.in_transaction
            return monitor_once(
                repository,
                configured,
                device_ids,
                enabled=enabled,
                probe=probes,
                clock=lambda: moment,
            )

        monkeypatch.setattr("nettracker.monitor.service.monitor_once", injected)
        monkeypatch.setattr("nettracker.config.load_settings", lambda *a, **k: settings)
        monkeypatch.setattr(loop, "run_periodic", partial(loop.run_periodic, wait=lambda _: False))
        monkeypatch.setattr(loop, "datetime", Mock(now=Mock(return_value=NOW)))
        yield Case(conn, settings, probes)
    finally:
        conn.close()


def test_default_never_prunes_even_with_enabled_config(
    case: Case, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prune = Mock(side_effect=AssertionError("pruning requires CLI opt-in"))
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", prune)
    assert loop.main(ARGS) == 0
    prune.assert_not_called()
    assert case.expired() == 5
    assert capsys.readouterr().out == "cycles=1 measurements=1\n"


def test_disabled_config_refuses_before_open_or_probe(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = case.settings.model_copy(
        update={"retention": case.settings.retention.model_copy(update={"enabled": False})}
    )
    monkeypatch.setattr("nettracker.config.load_settings", lambda *a, **k: settings)
    opened = Mock(side_effect=AssertionError("must refuse before opening"))
    monkeypatch.setattr("nettracker.db.connect", opened)
    assert loop.main([*ARGS, "--prune-ping"]) == 2
    opened.assert_not_called()
    case.probes.assert_not_called()
    assert case.expired() == 5


def test_cadence_single_batch_and_protected_tables(
    case: Case, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[int] = []

    def checked(conn: sqlite3.Connection, cutoff: str, *, batch_size: int, max_batches: int) -> int:
        assert not conn.in_transaction
        assert (batch_size, max_batches) == (2, 1)
        calls.append(case.probes.call_count)
        before = protected(conn)
        deleted = prune_ping_samples(conn, cutoff, batch_size=batch_size, max_batches=max_batches)
        assert protected(conn) == before
        return deleted

    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", checked)
    assert loop.main([*ARGS, "--prune-ping", "--prune-every-cycles", "2", "--cycles", "5"]) == 0
    assert calls == [2, 4]
    assert case.expired() == 1
    boundary = to_iso(NOW - timedelta(days=1))
    row = case.conn.execute(
        "SELECT COUNT(*) FROM sightings WHERE source='ping' AND seen_at=?", (boundary,)
    ).fetchone()
    assert row[0] == 1
    assert "pruned_ping_samples=4" in capsys.readouterr().out
    assert list(case.conn.execute("PRAGMA foreign_key_check")) == []


@pytest.mark.parametrize("value", ["0", "1000001"])
def test_invalid_cadence_fails_before_loading(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    load = Mock(side_effect=AssertionError("must validate first"))
    monkeypatch.setattr("nettracker.config.load_settings", load)
    with pytest.raises(SystemExit) as exc:
        loop.main([*ARGS, "--prune-ping", "--prune-every-cycles", value])
    assert exc.value.code == 2
    load.assert_not_called()


def test_cadence_without_opt_in_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    load = Mock()
    monkeypatch.setattr("nettracker.config.load_settings", load)
    with pytest.raises(SystemExit):
        loop.main([*ARGS, "--prune-every-cycles", "1"])
    load.assert_not_called()


@pytest.mark.parametrize("failure", [PingError("fixture"), ConfigError("fixture")])
def test_failed_cycle_never_prunes(
    case: Case, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr("nettracker.monitor.service.monitor_once", Mock(side_effect=failure))
    prune = Mock()
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", prune)
    assert loop.main([*ARGS, "--prune-ping", "--prune-every-cycles", "1"]) == 2
    prune.assert_not_called()
    assert case.expired() == 5


def test_stop_after_monitoring_skips_prune(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = Event()
    monkeypatch.setattr(loop, "Event", lambda: stopped)

    def stop(*args: object, **kwargs: object) -> int:
        stopped.set()
        return 0

    monkeypatch.setattr("nettracker.monitor.service.monitor_once", stop)
    prune = Mock()
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", prune)
    assert loop.main([*ARGS, "--prune-ping", "--prune-every-cycles", "1"]) == 0
    prune.assert_not_called()
    assert case.expired() == 5


def test_prune_error_is_explicit_and_restores_handler(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    prune = Mock(side_effect=DatabaseError("fixture"))
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", prune)
    assert loop.main([*ARGS, "--prune-ping", "--prune-every-cycles", "1"]) == 2
    prune.assert_called_once()
    assert signal.getsignal(signal.SIGTERM) == previous
    assert case.probes.call_count == 1
    assert case.expired() == 5


def test_refresh_failure_never_prunes(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = Mock(side_effect=ConfigError("fixture"))
    monkeypatch.setattr("nettracker.monitor.refresh.refresh_selected", refresh)
    prune = Mock()
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", prune)
    args = [*ARGS, "--refresh-passive", "--prune-ping", "--prune-every-cycles", "1"]
    assert loop.main(args) == 2
    case.probes.assert_not_called()
    prune.assert_not_called()
    assert case.expired() == 5
