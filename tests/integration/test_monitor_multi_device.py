"""Multi-device monitoring isolation on migrated SQLite with injected I/O and time."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.discovery_retention import retain_discovery
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.retention import cutoff_for, prune_ping_samples
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError
from nettracker.errors import ConfigError
from nettracker.monitor.loop import run_periodic
from nettracker.monitor.ping import PingResult
from nettracker.monitor.refresh import refresh_selected
from nettracker.monitor.service import monitor_once

START = datetime(2026, 10, 26, 12, tzinfo=UTC)
MACS = tuple(f"02:00:00:00:00:{number:02x}" for number in range(1, 5))
IPS = ("192.168.1.20", "192.168.1.21", "192.168.1.22")
NEW_IP = "192.168.1.30"


@dataclass
class Scenario:
    conn: sqlite3.Connection
    repo: MonitoringRepository
    settings: Settings
    ids: tuple[int, ...]
    unselected_id: int
    now: datetime = START
    addresses: list[str] = field(default_factory=lambda: list(IPS))
    online: tuple[bool, ...] = (True, True, True)
    probes: list[str] = field(default_factory=list)
    completed: int = 0
    missing: bool = False

    def read(self, subnets: list[IPv4Network]) -> list[Neighbor]:
        assert subnets == self.settings.allowed_subnets
        assert not self.conn.in_transaction
        neighbors = [Neighbor(ip, mac) for ip, mac in zip(self.addresses, MACS[:3], strict=True)]
        if self.missing:
            del neighbors[1]
        return [*neighbors, Neighbor("192.168.1.40", MACS[3])]

    def probe(self, ip: str) -> PingResult:
        assert not self.conn.in_transaction
        assert ip in self.addresses
        index = self.addresses.index(ip)
        self.probes.append(ip)
        online = self.online[index]
        return PingResult(1, int(online), float(index + 1) if online else None)

    def cycle(self) -> int:
        selected = [*self.ids, self.ids[0]]
        refreshed = refresh_selected(
            self.repo,
            self.settings,
            selected,
            enabled=True,
            reader=self.read,
            clock=lambda: self.now,
        )
        assert refreshed == 3
        count = monitor_once(
            self.repo,
            self.settings,
            selected,
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

    def counts(self) -> tuple[int, int, int]:
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM sightings WHERE source='discovery'), "
            "(SELECT COUNT(*) FROM sightings WHERE source='ping'), (SELECT COUNT(*) FROM scans)"
        ).fetchone()
        return int(row[0]), int(row[1]), int(row[2])

    def states(self) -> list[tuple[int, str, int, str]]:
        return [
            (int(row[0]), str(row[1]), int(row[2]), str(row[3]))
            for row in self.conn.execute(
                "SELECT device_id, ip, online, checked_at FROM monitor_state ORDER BY device_id"
            )
        ]

    def transitions(self) -> list[tuple[int, str]]:
        return [
            (int(row[0]), str(row[1]))
            for row in self.conn.execute(
                "SELECT device_id, kind FROM events WHERE kind IN ('online', 'offline') ORDER BY id"
            )
        ]

    def prune(self) -> tuple[int, int, int]:
        targets = [self.repo.target(value) for value in self.ids]
        states = self.states()
        result = retain_discovery(
            self.conn, self.now, keep_days=1, batch_size=100, max_batches=10, enabled=True
        )
        pings = prune_ping_samples(
            self.conn, cutoff_for(self.now, 1), batch_size=100, max_batches=10
        )
        assert [self.repo.target(value) for value in self.ids] == targets
        assert self.states() == states
        assert not self.conn.in_transaction
        return result.observations, pings, result.scans

    def assert_isolated(self) -> None:
        assert self.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 4
        unselected = self.conn.execute(
            "SELECT COUNT(*) FROM sightings WHERE device_id=?", (self.unselected_id,)
        ).fetchone()
        assert unselected[0] == 0
        state_ids = [
            int(row[0])
            for row in self.conn.execute("SELECT device_id FROM monitor_state ORDER BY device_id")
        ]
        assert state_ids == list(self.ids)
        known = self.conn.execute("SELECT COUNT(*) FROM devices WHERE status='known'").fetchone()
        assert known[0] == 4
        assert list(self.conn.execute("PRAGMA foreign_key_check")) == []
        assert not self.conn.in_transaction


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Iterator[Scenario]:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real cache, ping and user configuration are forbidden")

    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.config.load_settings", forbidden)
    conn = connect(":memory:")
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        ids = tuple(repo.upsert_device(mac, seen_at=START).id for mac in MACS)
        for device_id in ids:
            repo.set_status(device_id, "known")
        settings = Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "monitor": {"enabled": True, "max_observation_age_seconds": 60},
            }
        )
        yield Scenario(conn, repo, settings, ids[:3], ids[3])
    finally:
        conn.close()


def test_long_series_keeps_histories_separate_through_dhcp_and_retention(
    scenario: Scenario,
) -> None:
    def cycle() -> int:
        if scenario.completed == 1000:
            scenario.addresses[0] = NEW_IP
        count = scenario.cycle()
        if scenario.completed % 100 == 0:
            scenario.prune()
        return count

    result = run_periodic(cycle, cycles=2000, interval_seconds=60, wait=scenario.wait)
    assert (result.cycles, result.measurements, len(scenario.probes)) == (2000, 6000, 6000)
    assert scenario.now == START + timedelta(minutes=1999)
    assert scenario.prune() == (0, 0, 0)
    assert scenario.counts() == (4323, 4323, 1441)
    grouped = [
        tuple(row)
        for row in scenario.conn.execute(
            "SELECT device_id, ip, COUNT(*) FROM sightings WHERE source='ping' "
            "GROUP BY device_id, ip ORDER BY device_id, ip"
        )
    ]
    first, second, third = scenario.ids
    assert grouped == [
        (first, IPS[0], 441),
        (first, NEW_IP, 1000),
        (second, IPS[1], 1441),
        (third, IPS[2], 1441),
    ]
    assert [scenario.repo.target(value).ip for value in scenario.ids] == list(scenario.addresses)
    assert [state[2] for state in scenario.states()] == [1, 1, 1]
    assert scenario.transitions() == []
    scenario.assert_isolated()


def test_transitions_are_independent_for_selected_devices(scenario: Scenario) -> None:
    patterns = [(True, True, True), (False, True, False), (True, True, False), (True, False, True)]
    for pattern in patterns:
        scenario.online = pattern
        assert scenario.cycle() == 3
        scenario.wait(60)
    first, second, third = scenario.ids
    assert scenario.transitions() == [
        (first, "offline"),
        (third, "offline"),
        (first, "online"),
        (second, "offline"),
        (third, "online"),
    ]
    for device_id, index in zip(scenario.ids, range(3), strict=True):
        history = [
            (row[0], row[1])
            for row in scenario.conn.execute(
                "SELECT ip, online FROM sightings WHERE source='ping' AND device_id=? ORDER BY id",
                (device_id,),
            )
        ]
        assert history == [(IPS[index], int(pattern[index])) for pattern in patterns]
    assert scenario.counts() == (12, 12, 4)
    assert [state[2] for state in scenario.states()] == [1, 0, 1]
    assert len(scenario.probes) == 12
    scenario.assert_isolated()


@pytest.mark.parametrize("failure", ["missing", "shared-ip", "outside"])
def test_invalid_next_cache_does_not_partially_refresh_or_probe(
    scenario: Scenario, failure: str
) -> None:
    assert scenario.cycle() == 3
    before_counts = scenario.counts()
    before_states = scenario.states()
    before_targets = [scenario.repo.target(value) for value in scenario.ids]
    scenario.wait(60)
    if failure == "missing":
        scenario.missing = True
    elif failure == "shared-ip":
        scenario.addresses[1] = scenario.addresses[0]
    else:
        scenario.addresses[1] = "192.168.2.21"
    with pytest.raises((ConfigError, ScopeError)):
        scenario.cycle()
    assert scenario.completed == 1
    assert len(scenario.probes) == 3
    assert scenario.counts() == before_counts
    assert scenario.states() == before_states
    assert [scenario.repo.target(value) for value in scenario.ids] == before_targets
    assert scenario.transitions() == []
    scenario.assert_isolated()
