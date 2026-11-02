"""Temporary SQLite and synthetic context-managed Bbox port only."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import pytest

from nettracker.db.connection import connect
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository
from nettracker.routers.bbox_control import BboxControlPort
from nettracker.routers.bbox_control_service import BboxControlConfig, build_bbox_control
from nettracker.routers.bbox_session import BboxHost, BboxSnapshot
from nettracker.routers.control import AccessControlError

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MAC = "02:00:00:00:00:20"


class Port:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0
        self.writes = 0
        self.fail = False
        self.host = BboxHost(7, None, "192.168.1.20", MAC, True, False)

    @contextmanager
    def session(self) -> Iterator[BboxControlPort]:
        self.opens += 1
        try:
            yield self
        finally:
            self.closes += 1

    def snapshot(self) -> BboxSnapshot:
        return BboxSnapshot("synthetic-model", "synthetic-firmware", (self.host,), False)

    def set_blocked(self, identifier: int, *, blocked: bool) -> None:
        assert identifier == 7
        self.writes += 1
        self.host = replace(self.host, blocked=blocked)
        if self.fail:
            raise TimeoutError("synthetic failure")


def seed(path: Path, ip: str = "192.168.1.20") -> int:
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW)
        repo.add_sighting(device_id=device.id, ip=ip, online=True, seen_at=NOW)
        return device.id
    finally:
        conn.close()


def settings(path: Path) -> BboxControlConfig:
    return BboxControlConfig(
        database=path,
        networks=(IPv4Network("192.168.1.0/24"),),
        expected_model="synthetic-model",
        expected_firmware="synthetic-firmware",
        gateway_address=IPv4Address("192.168.1.1"),
        management_mac="02:00:00:00:00:02",
        gateway_mac="02:00:00:00:00:03",
        enabled=True,
    )


def test_confirmation_and_session_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    device_id = seed(path)
    port = Port()
    guard = build_bbox_control(settings(path), port.session, now=lambda: NOW)
    pending = guard.prepare(device_id, True, session_id="owner")
    assert port.opens == 0
    result = guard.confirm(pending.token, session_id="owner")
    assert result.changed is True
    assert (port.opens, port.closes, port.writes) == (1, 1, 1)
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")
    assert port.writes == 1


def test_changed_inventory_never_opens_session(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    device_id = seed(path)
    port = Port()
    guard = build_bbox_control(settings(path), port.session, now=lambda: NOW)
    pending = guard.prepare(device_id, True, session_id="owner")
    seed(path, "192.168.1.21")
    with pytest.raises(AccessControlError, match="ambiguous"):
        guard.confirm(pending.token, session_id="owner")
    assert port.opens == 0


def test_uncertain_failure_closes_session_and_consumes_token(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    device_id = seed(path)
    port = Port()
    port.fail = True
    guard = build_bbox_control(settings(path), port.session, now=lambda: NOW)
    pending = guard.prepare(device_id, True, session_id="owner")
    with pytest.raises(AccessControlError, match="uncertain"):
        guard.confirm(pending.token, session_id="owner")
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")
    assert (port.opens, port.closes, port.writes) == (1, 1, 1)


@pytest.mark.parametrize("mode", ["disabled", "protected", "gateway", "missing"])
def test_refusals_precede_session(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "inventory.db"
    ip = "192.168.1.1" if mode == "gateway" else "192.168.1.20"
    device_id = 1 if mode == "missing" else seed(path, ip)
    config = settings(path)
    if mode == "disabled":
        config = replace(config, enabled=False)
    elif mode == "protected":
        config = replace(config, management_mac=MAC)
    port = Port()
    guard = build_bbox_control(config, port.session, now=lambda: NOW)
    with pytest.raises(AccessControlError):
        guard.prepare(device_id, True, session_id="owner")
    assert port.opens == 0
    if mode == "missing":
        assert not path.exists()
