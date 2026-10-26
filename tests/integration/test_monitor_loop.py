"""Periodic monitoring on real SQLite migrations, with fake probes and fake waits only."""

import signal
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.discovery.scope import ScopeError
from nettracker.errors import ConfigError, DatabaseError
from nettracker.monitor.loop import main, run_periodic
from nettracker.monitor.ping import PingError, PingResult
from nettracker.monitor.service import monitor_once

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
IP = "192.168.1.20"


@dataclass
class Scenario:
    conn: sqlite3.Connection
    repo: MonitoringRepository
    settings: Settings
    moment: datetime = NOW
    probes: list[str] = field(default_factory=list)

    def probe(self, ip: str) -> PingResult:
        assert not self.conn.in_transaction
        self.probes.append(ip)
        return PingResult(1, 1, 1.0)

    def cycle(self) -> int:
        return monitor_once(
            self.repo,
            self.settings,
            [1],
            enabled=True,
            probe=self.probe,
            clock=lambda: self.moment,
        )

    def wait(self, seconds: float) -> bool:
        assert not self.conn.in_transaction
        self.moment += timedelta(seconds=seconds)
        return False

    @property
    def samples(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM sightings WHERE source = 'ping'").fetchone()
        return int(row[0])

    def observe(self, ip: str) -> None:
        self.repo.add_sighting(device_id=1, ip=ip, online=True, seen_at=self.moment)


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Scenario]:
    def forbidden(*args: object, **kwargs: object) -> PingResult:
        raise AssertionError("real ping backend is forbidden in integration tests")

    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    path = tmp_path / "periodic.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        repo.upsert_device("02:00:00:00:00:01", seen_at=NOW)
        settings = Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "database_path": str(path),
                "monitor": {"enabled": True, "max_observation_age_seconds": 60},
            }
        )
        case = Scenario(conn, repo, settings)
        case.observe(IP)
        yield case
    finally:
        conn.close()


def test_multiple_cycles_persist_distinct_samples(scenario: Scenario) -> None:
    result = run_periodic(scenario.cycle, cycles=3, interval_seconds=10, wait=scenario.wait)
    assert (result.cycles, result.measurements, scenario.samples) == (3, 3, 3)
    assert scenario.probes == [IP, IP, IP]
    assert not scenario.conn.in_transaction


def test_stale_discovery_stops_before_another_probe(scenario: Scenario) -> None:
    def expire(seconds: float) -> bool:
        return scenario.wait(61)

    with pytest.raises(ConfigError, match="stale"):
        run_periodic(scenario.cycle, cycles=3, wait=expire)
    assert scenario.probes == [IP]
    assert scenario.samples == 1


def test_dhcp_change_is_reloaded_on_next_cycle(scenario: Scenario) -> None:
    def changed(seconds: float) -> bool:
        scenario.wait(seconds)
        scenario.observe("192.168.1.21")
        return False

    result = run_periodic(scenario.cycle, cycles=2, interval_seconds=10, wait=changed)
    assert result.measurements == 2
    assert scenario.probes == [IP, "192.168.1.21"]
    rows = scenario.conn.execute(
        "SELECT ip FROM sightings WHERE source = 'ping' ORDER BY id"
    ).fetchall()
    assert [row[0] for row in rows] == [IP, "192.168.1.21"]


@pytest.mark.parametrize(
    "ip", ["192.168.2.20", "8.8.8.8", "::1", "192.168.1.0", "192.168.1.255"]
)
def test_changed_target_is_revalidated_before_probe(scenario: Scenario, ip: str) -> None:
    def changed(seconds: float) -> bool:
        scenario.wait(seconds)
        scenario.observe(ip)
        return False

    with pytest.raises(ScopeError):
        run_periodic(scenario.cycle, cycles=2, interval_seconds=10, wait=changed)
    assert scenario.probes == [IP]
    assert scenario.samples == 1


def test_ignored_device_stops_before_next_probe(scenario: Scenario) -> None:
    def ignored(seconds: float) -> bool:
        scenario.wait(seconds)
        scenario.repo.set_status(1, "ignored")
        return False

    with pytest.raises(DatabaseError):
        run_periodic(scenario.cycle, cycles=2, interval_seconds=10, wait=ignored)
    assert scenario.probes == [IP]
    assert scenario.samples == 1


def test_disabled_configuration_never_probes(scenario: Scenario) -> None:
    scenario.settings = scenario.settings.model_copy(
        update={"monitor": scenario.settings.monitor.model_copy(update={"enabled": False})}
    )
    with pytest.raises(ConfigError):
        run_periodic(scenario.cycle, cycles=2, wait=scenario.wait)
    assert scenario.probes == []
    assert scenario.samples == 0


def test_failed_second_cycle_keeps_only_previously_committed_samples(scenario: Scenario) -> None:
    other = scenario.repo.upsert_device("02:00:00:00:00:02", seen_at=NOW)
    scenario.repo.add_sighting(device_id=other.id, ip="192.168.1.21", online=True, seen_at=NOW)

    def probe(ip: str) -> PingResult:
        scenario.probes.append(ip)
        if len(scenario.probes) == 4:
            raise PingError("fixture transport failure")
        return PingResult(1, 1, 1.0)

    def cycle() -> int:
        return monitor_once(
            scenario.repo,
            scenario.settings,
            [1, other.id],
            enabled=True,
            probe=probe,
            clock=lambda: scenario.moment,
        )

    with pytest.raises(PingError):
        run_periodic(cycle, cycles=2, interval_seconds=10, wait=scenario.wait)
    assert scenario.samples == 2
    assert len(scenario.probes) == 4
    assert not scenario.conn.in_transaction


def test_cli_runs_one_real_sqlite_cycle_with_injected_probe(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "nettracker.config.load_settings", lambda *args, **kwargs: scenario.settings
    )

    def injected(
        repo: MonitoringRepository,
        settings: Settings,
        device_ids: Sequence[int],
        *,
        enabled: bool = False,
    ) -> int:
        return monitor_once(
            repo,
            settings,
            device_ids,
            enabled=enabled,
            probe=scenario.probe,
            clock=lambda: scenario.moment,
        )

    monkeypatch.setattr("nettracker.monitor.service.monitor_once", injected)
    previous = signal.getsignal(signal.SIGTERM)
    assert main(["--device-id", "1", "--enable-monitoring"]) == 0
    assert "cycles=1 measurements=1" in capsys.readouterr().out
    assert scenario.samples == 1
    assert scenario.probes == [IP]
    assert signal.getsignal(signal.SIGTERM) == previous
