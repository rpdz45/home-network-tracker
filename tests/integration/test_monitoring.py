"""Monitoring on temporary SQLite with invented devices, time and fake probes only."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from nettracker.cli import main
from nettracker.config import MonitorSettings, Settings
from nettracker.db import LATEST_VERSION, connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.discovery.scope import ScopeError
from nettracker.errors import ConfigError, DatabaseError
from nettracker.monitor.ping import PingError, PingResult
from nettracker.monitor.service import monitor_once

T0 = datetime(2026, 1, 1, tzinfo=UTC)
IP = "192.168.1.2"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "monitor.db", timeout=0.01)
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> MonitoringRepository:
    return MonitoringRepository(conn)


def settings(enabled: bool = True) -> Settings:
    return Settings(
        allowed_subnets=["192.168.1.0/24"],  # type: ignore[list-item]
        monitor=MonitorSettings(enabled=enabled),
    )


def seed(
    repo: MonitoringRepository, *, ip: str = IP, mac: str = "02:11:22:33:44:55", when: datetime = T0
) -> int:
    device = repo.upsert_device(mac, seen_at=when)
    repo.add_sighting(device_id=device.id, ip=ip, online=True, seen_at=when)
    return device.id


def test_transitions_idempotency_and_ip_change(
    repo: MonitoringRepository, conn: sqlite3.Connection
) -> None:
    device = seed(repo)
    repo.set_status(device, "to_confirm")
    good, bad = PingResult(3, 2, 2.0), PingResult(3, 0, None)
    for step, result in enumerate([good, good, bad, bad, good], 1):
        moment = T0 + timedelta(seconds=step)
        assert (
            monitor_once(
                repo,
                settings(),
                [device, device],
                enabled=True,
                probe=Mock(return_value=result),
                clock=partial(lambda value: value, moment),
            )
            == 1
        )
        assert (
            monitor_once(
                repo,
                settings(),
                [device],
                enabled=True,
                probe=Mock(return_value=result),
                clock=partial(lambda value: value, moment),
            )
            == 0
        )
    events = repo.list_events()
    assert [event.kind for event in events] == ["online", "offline"]
    assert conn.execute("SELECT COUNT(*) FROM sightings WHERE source='ping'").fetchone()[0] == 5
    row = conn.execute(
        "SELECT latency_ms, packet_loss_pct FROM sightings WHERE source='ping' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(row) == (2.0, pytest.approx(100 / 3))
    assert repo.get_device(device).last_seen == T0.isoformat(timespec="microseconds")  # type: ignore[union-attr]
    assert repo.get_device(device).status == "to_confirm"  # type: ignore[union-attr]
    later = T0 + timedelta(seconds=6)
    seed(repo, ip="192.168.1.3", when=later)
    target = repo.target(device)
    assert target.ip == "192.168.1.3"
    assert (
        monitor_once(
            repo, settings(), [device], enabled=True, probe=lambda _: bad, clock=lambda: later
        )
        == 1
    )
    assert len(repo.list_events()) == 2  # New IP starts a new baseline, not a false transition.
    with pytest.raises(DatabaseError, match="backwards"):
        repo.record(target, online=True, latency_ms=1.0, packet_loss_pct=0, checked_at=T0)


@pytest.mark.parametrize(("configured", "flag"), [(False, False), (False, True), (True, False)])
def test_double_opt_in(repo: MonitoringRepository, configured: bool, flag: bool) -> None:
    forbidden = Mock(side_effect=AssertionError("packets forbidden"))
    with pytest.raises(ConfigError):
        monitor_once(repo, settings(configured), [1], enabled=flag, probe=forbidden)
    forbidden.assert_not_called()


@pytest.mark.parametrize("ids", [[], [0], [-1], [True], list(range(1, 66))])
def test_invalid_selection(repo: MonitoringRepository, ids: list[int]) -> None:
    with pytest.raises(ConfigError):
        monitor_once(repo, settings(), ids, enabled=True, probe=Mock())


@pytest.mark.parametrize("ip", ["8.8.8.8", "192.168.2.2", "::1", "192.168.1.0", "192.168.1.255"])
def test_entire_batch_validated_before_probe(repo: MonitoringRepository, ip: str) -> None:
    first = seed(repo)
    second = seed(repo, ip=ip, mac="00:11:22:33:44:66")
    forbidden = Mock(side_effect=AssertionError("packets forbidden"))
    with pytest.raises(ScopeError):
        monitor_once(
            repo, settings(), [first, second], enabled=True, probe=forbidden, clock=lambda: T0
        )
    forbidden.assert_not_called()


@pytest.mark.parametrize("elapsed", [-1, 1801])
def test_stale_or_future_discovery(repo: MonitoringRepository, elapsed: int) -> None:
    device = seed(repo)
    forbidden = Mock()
    with pytest.raises(ConfigError, match="stale"):
        monitor_once(
            repo,
            settings(),
            [device],
            enabled=True,
            probe=forbidden,
            clock=lambda: T0 + timedelta(seconds=elapsed),
        )
    forbidden.assert_not_called()


def test_missing_ignored_merged_and_unobserved_targets(
    repo: MonitoringRepository, conn: sqlite3.Connection
) -> None:
    with pytest.raises(DatabaseError, match="existing"):
        repo.target(999)
    device = repo.upsert_device("00:11:22:33:44:55", seen_at=T0)
    with pytest.raises(DatabaseError, match="no discovery"):
        repo.target(device.id)
    repo.set_status(device.id, "ignored")
    with pytest.raises(DatabaseError, match="non-ignored"):
        repo.target(device.id)
    repo.set_status(device.id, "known")
    other = seed(repo)
    conn.execute("UPDATE devices SET merged_into=? WHERE id=?", (other, device.id))
    with pytest.raises(DatabaseError):
        repo.target(device.id)


def test_ip_conflict_and_claim_released(repo: MonitoringRepository) -> None:
    first = seed(repo)
    second = seed(repo, mac="00:11:22:33:44:66")
    with pytest.raises(DatabaseError, match="ambiguous"):
        repo.target(first)
    with pytest.raises(DatabaseError):
        repo.target(second)
    seed(repo, ip="192.168.1.3", mac="00:11:22:33:44:66", when=T0 + timedelta(seconds=1))
    assert repo.target(first).ip == IP
    seed(repo, ip=IP, mac="00:11:22:33:44:66", when=T0 + timedelta(seconds=2))
    with pytest.raises(DatabaseError, match="newer"):
        repo.target(first)


@pytest.mark.parametrize("failure", [PingError("permission"), KeyboardInterrupt()])
def test_transport_failure_or_sigint_leaves_no_samples(
    repo: MonitoringRepository, conn: sqlite3.Connection, failure: BaseException
) -> None:
    first = seed(repo)
    second = seed(repo, ip="192.168.1.3", mac="00:11:22:33:44:66")
    fake = Mock(side_effect=[PingResult(1, 1, 1.0), failure])
    with pytest.raises(type(failure)):
        monitor_once(repo, settings(), [first, second], enabled=True, probe=fake, clock=lambda: T0)
    assert conn.execute("SELECT COUNT(*) FROM monitor_state").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sightings WHERE source='ping'").fetchone()[0] == 0


def test_concurrent_discovery_rolls_back_whole_cycle(
    repo: MonitoringRepository, conn: sqlite3.Connection
) -> None:
    first = seed(repo)
    second = seed(repo, ip="192.168.1.3", mac="00:11:22:33:44:66")

    def fake(ip: str) -> PingResult:
        assert not conn.in_transaction
        if ip == "192.168.1.3":
            seed(repo, ip="192.168.1.4", mac="00:11:22:33:44:66", when=T0 + timedelta(seconds=1))
        return PingResult(1, 1, 1.0)

    with pytest.raises(DatabaseError, match="changed"):
        monitor_once(
            repo,
            settings(),
            [first, second],
            enabled=True,
            probe=fake,
            clock=lambda: T0 + timedelta(seconds=2),
        )
    assert conn.execute("SELECT COUNT(*) FROM monitor_state").fetchone()[0] == 0


def test_backwards_cycle_clock(repo: MonitoringRepository) -> None:
    device = seed(repo)
    moments = iter([T0 + timedelta(seconds=1), T0])
    with pytest.raises(ConfigError, match="backwards"):
        monitor_once(
            repo,
            settings(),
            [device],
            enabled=True,
            probe=lambda _: PingResult(1, 1, 1.0),
            clock=lambda: next(moments),
        )


@pytest.mark.parametrize(
    ("online", "latency", "loss"),
    [
        (True, 1.0, float("nan")),
        (False, None, 0.0),
        (True, float("inf"), 0.0),
        (True, None, 0.0),
        (False, 1.0, 100.0),
    ],
)
def test_repository_rejects_invalid_measurement(
    repo: MonitoringRepository, online: bool, latency: float | None, loss: float
) -> None:
    device = seed(repo)
    with pytest.raises(ValueError):
        repo.record(
            repo.target(device),
            online=online,
            latency_ms=latency,
            packet_loss_pct=loss,
            checked_at=T0,
        )


def test_database_locked_is_explicit(
    repo: MonitoringRepository, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    device = seed(repo)
    other = connect(tmp_path / "monitor.db", timeout=0.01)
    try:
        other.execute("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseError, match="locked"):
            repo.record(
                repo.target(device), online=True, latency_ms=1.0, packet_loss_pct=0, checked_at=T0
            )
        assert not conn.in_transaction
    finally:
        other.close()


def test_migrate_v1_preserves_discovery(tmp_path: Path) -> None:
    from nettracker.db.migrations import _V1, _apply

    conn = connect(tmp_path / "v1.db")
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        _apply(conn, 1, _V1)
        repo = MonitoringRepository(conn)
        device = seed(repo)
        assert migrate(conn) == LATEST_VERSION
        assert repo.target(device).ip == IP
        assert conn.execute("SELECT source FROM sightings").fetchone()[0] == "discovery"
        assert migrate(conn) == LATEST_VERSION
    finally:
        conn.close()


def test_config_bounds() -> None:
    assert MonitorSettings().enabled is False
    for kwargs in [{"packets": 0}, {"packets": 6}, {"max_observation_age_seconds": 59}]:
        with pytest.raises(ValidationError):
            MonitorSettings.model_validate(kwargs)


def test_cli_opt_in_success_and_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("NETTRACKER_CONFIG", "NETTRACKER_DATABASE_PATH", "NETTRACKER_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "config.toml"
    config.write_text(
        'allowed_subnets=["192.168.1.0/24"]\ndatabase_path="cli.db"\n[monitor]\nenabled=true\n',
        encoding="utf-8",
    )
    args = ["monitor-once", "--device-id", "1"]
    assert main(args) == 1
    assert not (tmp_path / "cli.db").exists()
    fake = Mock(return_value=1)
    monkeypatch.setattr("nettracker.cli.monitor_once", fake)
    assert main([*args, "--enable-monitoring"]) == 0
    assert fake.call_args.kwargs["enabled"] is True
    fake.side_effect = KeyboardInterrupt
    assert main([*args, "--enable-monitoring"]) == 130
    assert "interrupted" in capsys.readouterr().err
    config.write_text('allowed_subnets=["192.168.1.0/24"]\n', encoding="utf-8")
    fake.reset_mock()
    assert main([*args, "--enable-monitoring"]) == 1
    fake.assert_not_called()


def test_service_wires_real_backend_only_through_mock(
    repo: MonitoringRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = seed(repo)
    backend = Mock(return_value=PingResult(3, 1, 1.0))
    monkeypatch.setattr("nettracker.monitor.service.probe_ping", backend)
    assert monitor_once(repo, settings(), [device], enabled=True, clock=lambda: T0) == 1
    backend.assert_called_once_with(
        IP, settings().allowed_subnets, enabled=True, packets=3, timeout=1.0
    )


def test_open_transaction_never_reaches_network(repo: MonitoringRepository) -> None:
    device = seed(repo)
    forbidden = Mock()
    with repo.transaction(), pytest.raises(ConfigError, match="open database transaction"):
        monitor_once(repo, settings(), [device], enabled=True, probe=forbidden, clock=lambda: T0)
    forbidden.assert_not_called()
