"""Offline collector tests with a fake repository and injected neighbor reader."""

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Network
from typing import Any, cast

import pytest

from nettracker.db.repository import Repository
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class FakeDevice:
    id: int
    is_randomized_mac: bool


class FakeRepository:
    def __init__(self) -> None:
        self.devices: dict[str, FakeDevice] = {}
        self.scans: list[str] = []
        self.events: list[str] = []
        self.sightings: list[str] = []
        self.statuses: list[str] = []

    def start_scan(self, **kwargs: Any) -> int:
        self.scans.append("started")
        return len(self.scans)

    def finish_scan(self, scan_id: int, **kwargs: Any) -> None:
        self.scans.append(kwargs["status"])

    def transaction(self) -> Any:
        return nullcontext()

    def get_device_by_mac(self, mac: str) -> FakeDevice | None:
        return self.devices.get(mac)

    def upsert_device(self, mac: str, **kwargs: Any) -> FakeDevice:
        return self.devices.setdefault(mac, FakeDevice(len(self.devices) + 1, mac.startswith("02")))

    def set_status(self, device_id: int, status: str) -> None:
        self.statuses.append(status)

    def add_event(self, kind: str, **kwargs: Any) -> None:
        self.events.append(kind)

    def add_sighting(self, **kwargs: Any) -> None:
        self.sightings.append(kwargs["ip"])


def test_first_discovery_creates_events_without_duplicate_alerts() -> None:
    repo = FakeRepository()
    entries = [
        Neighbor("192.168.1.2", "00:11:22:33:44:55"),
        Neighbor("192.168.1.2", "00:11:22:33:44:55"),
        Neighbor("192.168.1.3", "02:11:22:33:44:66"),
    ]

    def read(subnets: list[IPv4Network]) -> list[Neighbor]:
        assert subnets == ALLOWED
        return entries

    assert collect_passive(cast(Repository, repo), ALLOWED, reader=read, clock=lambda: NOW) == 2
    assert repo.events == ["new_device", "to_confirm"]
    assert repo.statuses == ["to_confirm"]
    assert len(repo.sightings) == 2
    assert collect_passive(cast(Repository, repo), ALLOWED, reader=read, clock=lambda: NOW) == 2
    assert repo.events == ["new_device", "to_confirm"]
    assert repo.scans == ["started", "ok", "started", "ok"]


def test_reader_failure_marks_scan_error() -> None:
    repo = FakeRepository()

    def read(subnets: list[IPv4Network]) -> list[Neighbor]:
        raise RuntimeError("unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        collect_passive(cast(Repository, repo), ALLOWED, reader=read, clock=lambda: NOW)
    assert repo.scans == ["started", "error"]
    assert not repo.events


def test_outside_scope_never_persisted_even_if_reader_is_broken() -> None:
    repo = FakeRepository()
    with pytest.raises(ScopeError):
        collect_passive(
            cast(Repository, repo),
            ALLOWED,
            reader=lambda _: [Neighbor("8.8.8.8", "00:11:22:33:44:55")],
            clock=lambda: NOW,
        )
    assert repo.scans == ["started", "error"]
    assert not repo.sightings


def test_empty_scope_rejected_before_starting_a_scan() -> None:
    repo = FakeRepository()
    with pytest.raises(ValueError, match="allowed_subnets"):
        collect_passive(cast(Repository, repo), [], clock=lambda: NOW)
    assert repo.scans == []
