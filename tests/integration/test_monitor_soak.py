"""Simulated monitoring endurance and retention on real in-memory SQLite migrations."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.discovery_retention import retain_discovery
from nettracker.db.health import collector_health
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.retention import cutoff_for, prune_ping_samples
from nettracker.discovery.passive import Neighbor, NeighborReadError
from nettracker.errors import ConfigError
from nettracker.monitor.loop import run_periodic
from nettracker.monitor.ping import PingResult
from nettracker.monitor.refresh import refresh_selected
from nettracker.monitor.service import monitor_once

START = datetime(2026, 10, 26, 12, tzinfo=UTC)
MAC = "02:00:00:00:00:01"
IP = "192.168.1.20"
NEW_IP = "192.168.1.21"


@dataclass
class Scenario:
    conn: sqlite3.Connection
    repo: MonitoringRepository
    settings: Settings
    now: datetime = START
    neighbors: list[Neighbor] = field(default_factory=lambda: [Neighbor(IP, MAC)])
    online: bool = True
    read_error: bool = False
    completed: int = 0
    probes: int = 0
    removed_observations: int = 0
    removed_scans: int = 0
    removed_pings: int = 0

    def read(self, subnets: list[IPv4Network]) -> list[Neighbor]:
        assert subnets == self.settings.allowed_subnets
        assert not self.conn.in_transaction
        if self.read_error:
            raise NeighborReadError("fixture cache failure")
        return self.neighbors

    def probe(self, ip: str) -> PingResult:
        assert ip in (IP, NEW_IP)
        assert not self.conn.in_transaction
        self.probes += 1
        return PingResult(1, int(self.online), 1.0 if self.online else None)

    def cycle(self) -> int:
        refresh_selected(
            self.repo,
            self.settings,
            [1],
            enabled=True,
            reader=self.read,
            clock=lambda: self.now,
        )
        count = monitor_once(
            self.repo,
            self.settings,
            [1],
            enabled=True,
            probe=self.probe,
            clock=lambda: self.now,
        )
        self.completed += 1
        return count

    def wait(self, seconds: float) -> bool:
        assert not self.conn.in_transaction
        self.now += timedelta(seconds=seconds)
        return False

    def prune(self) -> None:
        target = self.repo.target(1)
        health = collector_health(self.conn, self.now, 300)
        result = retain_discovery(
            self.conn, self.now, keep_days=1, batch_size=100, max_batches=10, enabled=True
        )
        self.removed_observations += result.observations
        self.removed_scans += result.scans
        self.removed_pings += prune_ping_samples(
            self.conn, cutoff_for(self.now, 1), batch_size=100, max_batches=10
        )
        assert self.repo.target(1) == target
        assert collector_health(self.conn, self.now, 300) == health
        assert not self.conn.in_transaction

    def counts(self) -> tuple[int, int, int]:
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM sightings WHERE source='discovery'), "
            "(SELECT COUNT(*) FROM sightings WHERE source='ping'), (SELECT COUNT(*) FROM scans)"
        ).fetchone()
        return int(row[0]), int(row[1]), int(row[2])


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Iterator[Scenario]:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real cache and ping backends are forbidden")

    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    conn = connect(":memory:")
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        repo.upsert_device(MAC, seen_at=START)
        settings = Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "monitor": {"enabled": True, "max_observation_age_seconds": 60},
            }
        )
        yield Scenario(conn, repo, settings)
    finally:
        conn.close()


def test_two_thousand_cycles_with_dhcp_and_repeated_retention(scenario: Scenario) -> None:
    def cycle() -> int:
        if scenario.completed == 1000:
            scenario.neighbors = [Neighbor(NEW_IP, MAC)]
        count = scenario.cycle()
        if scenario.completed % 100 == 0:
            scenario.prune()
        return count

    result = run_periodic(cycle, cycles=2000, interval_seconds=60, wait=scenario.wait)
    scenario.prune()
    assert (result.cycles, result.measurements, scenario.probes) == (2000, 2000, 2000)
    assert scenario.now == START + timedelta(minutes=1999)
    assert scenario.counts() == (1441, 1441, 1441)
    assert scenario.removed_observations == 559
    assert scenario.removed_pings == 559
    assert scenario.removed_scans == 559
    assert scenario.repo.target(1).ip == NEW_IP
    grouped = [
        (row[0], row[1])
        for row in scenario.conn.execute(
            "SELECT ip, COUNT(*) FROM sightings WHERE source='ping' GROUP BY ip ORDER BY ip"
        )
    ]
    assert grouped == [(IP, 441), (NEW_IP, 1000)]
    assert scenario.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
    assert scenario.conn.execute("SELECT COUNT(*) FROM monitor_state").fetchone()[0] == 1
    assert list(scenario.conn.execute("PRAGMA foreign_key_check")) == []


@pytest.mark.parametrize("failure", ["missing", "ambiguous", "reader-error"])
def test_second_cycle_cache_failure_never_reuses_previous_target(
    scenario: Scenario, failure: str
) -> None:
    def wait(seconds: float) -> bool:
        scenario.wait(seconds)
        if failure == "missing":
            scenario.neighbors = []
        elif failure == "ambiguous":
            scenario.neighbors = [Neighbor(IP, MAC), Neighbor(IP, "02:00:00:00:00:02")]
        else:
            scenario.read_error = True
        return False

    with pytest.raises((ConfigError, NeighborReadError)):
        run_periodic(scenario.cycle, cycles=3, interval_seconds=60, wait=wait)
    assert (scenario.completed, scenario.probes) == (1, 1)
    assert scenario.counts() == (1, 1, 1)
    assert not scenario.conn.in_transaction


def test_transitions_survive_pruned_ping_history(scenario: Scenario) -> None:
    for online in (True, False, True):
        scenario.online = online
        assert scenario.cycle() == 1
        scenario.prune()
        scenario.now += timedelta(days=2)
    kinds = [row[0] for row in scenario.conn.execute("SELECT kind FROM events ORDER BY id")]
    assert kinds == ["offline", "online"]
    assert scenario.counts() == (1, 1, 1)
    assert scenario.removed_pings == 2
    assert scenario.conn.execute("SELECT online FROM monitor_state").fetchone()[0] == 1
    assert list(scenario.conn.execute("PRAGMA foreign_key_check")) == []
