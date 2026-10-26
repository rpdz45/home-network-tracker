"""Selected passive refresh on real SQLite; no cache commands or ping subprocesses."""

import signal
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.discovery.passive import Neighbor, NeighborReadError
from nettracker.discovery.scope import ScopeError
from nettracker.errors import ConfigError, DatabaseError
from nettracker.monitor.loop import main
from nettracker.monitor.ping import PingResult
from nettracker.monitor.refresh import refresh_selected
from nettracker.monitor.service import monitor_once

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
MAC = "02:00:00:00:00:01"
OTHER = "02:00:00:00:00:02"
IP = "192.168.1.20"
NEW_IP = "192.168.1.21"


@dataclass
class Case:
    conn: sqlite3.Connection
    repo: MonitoringRepository
    settings: Settings


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Case]:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real network/cache backend is forbidden")

    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    path = tmp_path / "refresh.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        before = NOW - timedelta(hours=1)
        repo.upsert_device(MAC, seen_at=before)
        repo.add_sighting(device_id=1, ip=IP, online=True, seen_at=before)
        settings = Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "database_path": str(path),
                "monitor": {"enabled": True, "max_observation_age_seconds": 60},
            }
        )
        yield Case(conn, repo, settings)
    finally:
        conn.close()


def test_refresh_changes_ip_without_enrolling_unselected_devices(case: Case) -> None:
    snapshot = [Neighbor(NEW_IP, MAC), Neighbor("192.168.1.22", OTHER), Neighbor(NEW_IP, MAC)]
    reader = Mock(return_value=snapshot)
    count = refresh_selected(
        case.repo, case.settings, [1, 1], enabled=True, reader=reader, clock=lambda: NOW
    )
    assert count == 1
    assert reader.call_count == 1
    assert case.repo.target(1).ip == NEW_IP
    assert case.repo.get_device_by_mac(OTHER) is None
    device = case.repo.get_device(1)
    assert device is not None and device.status == "unknown"
    probe = Mock(return_value=PingResult(1, 1, 1.0))
    assert (
        monitor_once(case.repo, case.settings, [1], enabled=True, probe=probe, clock=lambda: NOW)
        == 1
    )
    probe.assert_called_once_with(NEW_IP)
    assert not case.conn.in_transaction


@pytest.mark.parametrize(
    "snapshot",
    [
        [],
        [Neighbor(IP, OTHER)],
        [Neighbor(IP, MAC), Neighbor(IP, OTHER)],
        [Neighbor(IP, MAC), Neighbor(NEW_IP, MAC)],
    ],
)
def test_missing_or_ambiguous_cache_does_not_refresh(case: Case, snapshot: list[Neighbor]) -> None:
    previous = case.repo.target(1)
    with pytest.raises(ConfigError):
        refresh_selected(
            case.repo,
            case.settings,
            [1],
            enabled=True,
            reader=lambda _: snapshot,
            clock=lambda: NOW,
        )
    assert case.repo.target(1) == previous
    assert case.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0


@pytest.mark.parametrize("ip", ["8.8.8.8", "192.168.2.20", "::1", "192.168.1.0", "192.168.1.255"])
def test_invalid_scope_is_rejected_before_writes(case: Case, ip: str) -> None:
    with pytest.raises(ScopeError):
        refresh_selected(
            case.repo,
            case.settings,
            [1],
            enabled=True,
            reader=lambda _: [Neighbor(ip, MAC)],
            clock=lambda: NOW,
        )
    assert case.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0


@pytest.mark.parametrize("mac", ["not-a-mac", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"])
def test_invalid_mac_is_rejected_before_writes(case: Case, mac: str) -> None:
    with pytest.raises(ConfigError):
        refresh_selected(
            case.repo,
            case.settings,
            [1],
            enabled=True,
            reader=lambda _: [Neighbor(IP, mac)],
            clock=lambda: NOW,
        )
    assert case.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["no-opt-in", "disabled-config", "active-scan", "ignored"])
def test_guard_failures_do_not_read_cache(case: Case, mode: str) -> None:
    settings = case.settings
    if mode == "disabled-config":
        settings = settings.model_copy(
            update={"monitor": settings.monitor.model_copy(update={"enabled": False})}
        )
    if mode == "active-scan":
        settings = settings.model_copy(
            update={"scan": settings.scan.model_copy(update={"mode": "active"})}
        )
    if mode == "ignored":
        case.repo.set_status(1, "ignored")
    reader = Mock()
    with pytest.raises((ConfigError, DatabaseError)):
        refresh_selected(case.repo, settings, [1], enabled=mode != "no-opt-in", reader=reader)
    reader.assert_not_called()


@pytest.mark.parametrize("ids", [[], [0], [True], [999], [1] * 65])
def test_invalid_selection_does_not_read_cache(case: Case, ids: list[int]) -> None:
    reader = Mock()
    with pytest.raises((ConfigError, DatabaseError)):
        refresh_selected(case.repo, case.settings, ids, enabled=True, reader=reader)
    reader.assert_not_called()


def test_open_transaction_does_not_read_cache(case: Case) -> None:
    reader = Mock()
    with case.repo.transaction(), pytest.raises(ConfigError):
        refresh_selected(case.repo, case.settings, [1], enabled=True, reader=reader)
    reader.assert_not_called()


def test_cache_failure_or_size_limit_does_not_create_scan(case: Case) -> None:
    for reader in (
        Mock(side_effect=NeighborReadError("fixture")),
        Mock(return_value=[Neighbor(IP, MAC)] * 4097),
    ):
        with pytest.raises((NeighborReadError, ConfigError)):
            refresh_selected(case.repo, case.settings, [1], enabled=True, reader=reader)
    assert case.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0


def test_cli_refresh_precedes_monitoring(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nettracker.config.load_settings", lambda *args, **kwargs: case.settings)
    calls: list[str] = []

    def refresh(
        repo: MonitoringRepository, settings: Settings, ids: Sequence[int], *, enabled: bool = False
    ) -> int:
        calls.append("refresh")
        return refresh_selected(
            repo,
            settings,
            ids,
            enabled=enabled,
            reader=lambda _: [Neighbor(NEW_IP, MAC)],
            clock=lambda: NOW,
        )

    def monitor(
        repo: MonitoringRepository, settings: Settings, ids: Sequence[int], *, enabled: bool = False
    ) -> int:
        calls.append("monitor")
        return monitor_once(
            repo,
            settings,
            ids,
            enabled=enabled,
            probe=lambda _: PingResult(1, 1, 1.0),
            clock=lambda: NOW,
        )

    monkeypatch.setattr("nettracker.monitor.refresh.refresh_selected", refresh)
    monkeypatch.setattr("nettracker.monitor.service.monitor_once", monitor)
    assert main(["--device-id", "1", "--enable-monitoring", "--refresh-passive"]) == 0
    assert calls == ["refresh", "monitor"]


def test_cli_cache_failure_never_calls_monitor(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nettracker.config.load_settings", lambda *args, **kwargs: case.settings)
    refresh = Mock(side_effect=NeighborReadError("fixture"))
    monitor = Mock()
    monkeypatch.setattr("nettracker.monitor.refresh.refresh_selected", refresh)
    monkeypatch.setattr("nettracker.monitor.service.monitor_once", monitor)
    assert main(["--device-id", "1", "--enable-monitoring", "--refresh-passive"]) == 2
    monitor.assert_not_called()


def test_stop_during_refresh_skips_ping(case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nettracker.config.load_settings", lambda *args, **kwargs: case.settings)

    def stop(*args: object, **kwargs: object) -> int:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        return 1

    monitor = Mock()
    monkeypatch.setattr("nettracker.monitor.refresh.refresh_selected", stop)
    monkeypatch.setattr("nettracker.monitor.service.monitor_once", monitor)
    previous = signal.getsignal(signal.SIGTERM)
    assert main(["--device-id", "1", "--enable-monitoring", "--refresh-passive"]) == 0
    monitor.assert_not_called()
    assert signal.getsignal(signal.SIGTERM) == previous
