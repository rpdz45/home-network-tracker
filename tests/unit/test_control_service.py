"""Compose real services with synthetic SQLite and MockTransport only."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from nettracker.db.connection import connect
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository
from nettracker.routers.control import AccessControlError
from nettracker.routers.control_service import LiveboxControlConfig, build_livebox_control

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MAC = "02:00:00:00:00:20"


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


def settings(path: Path) -> LiveboxControlConfig:
    return LiveboxControlConfig(
        database=path,
        base_url="https://192.168.1.1",
        networks=(IPv4Network("192.168.1.0/24"),),
        password=SecretStr("synthetic-test-password"),
        expected_firmware="synthetic-firmware",
        management_mac="02:00:00:00:00:02",
        gateway_mac="02:00:00:00:00:03",
        enabled=True,
    )


def forbidden(request: httpx.Request) -> httpx.Response:
    pytest.fail("refused actions must not contact the router")


def test_confirmed_inventory_target_reaches_adapter_once(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    device_id = seed(path)
    calls: list[str] = []
    override = ""

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal override
        payload = json.loads(request.content)
        method = payload["method"]
        calls.append(method)
        if method == "get":
            return httpx.Response(
                200,
                json={
                    "status": {"ProductClass": "Livebox 5", "SoftwareVersion": "synthetic-firmware"}
                },
            )
        if method == "createContext":
            return httpx.Response(200, json={"data": {"contextID": "test-context"}})
        assert payload["parameters"]["ID"] == MAC.upper()
        if method == "overrideSchedule":
            override = payload["parameters"]["override"]
            return httpx.Response(200, json={"status": True})
        return httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "scheduleInfo": {
                        "enable": True,
                        "override": override,
                        "value": "Disable" if override else "Enable",
                    }
                },
            },
        )

    guard = build_livebox_control(
        settings(path), transport=httpx.MockTransport(handle), now=lambda: NOW
    )
    pending = guard.prepare(device_id, True, session_id="owner")
    assert calls == []
    result = guard.confirm(pending.token, session_id="owner")
    assert result.changed is True
    assert calls == ["get", "createContext", "getSchedule", "overrideSchedule", "getSchedule"]
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")
    assert calls.count("overrideSchedule") == 1


def test_inventory_change_prevents_http(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    device_id = seed(path)
    guard = build_livebox_control(
        settings(path), transport=httpx.MockTransport(forbidden), now=lambda: NOW
    )
    pending = guard.prepare(device_id, True, session_id="owner")
    seed(path, "192.168.1.21")
    with pytest.raises(AccessControlError, match="ambiguous"):
        guard.confirm(pending.token, session_id="owner")


@pytest.mark.parametrize("mode", ["disabled", "protected", "missing"])
def test_refusals_never_connect(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "inventory.db"
    device_id = 1 if mode == "missing" else seed(path)
    config = settings(path)
    if mode == "disabled":
        config = replace(config, enabled=False)
    elif mode == "protected":
        config = replace(config, management_mac=MAC)
    guard = build_livebox_control(config, transport=httpx.MockTransport(forbidden), now=lambda: NOW)
    with pytest.raises(AccessControlError):
        guard.prepare(device_id, True, session_id="owner")
    if mode == "missing":
        assert not path.exists()
