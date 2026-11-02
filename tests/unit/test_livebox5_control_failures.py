"""Failure injection for Livebox control; all HTTP uses MockTransport."""

import json
from ipaddress import IPv4Address, IPv4Network

import httpx
import pytest
from pydantic import SecretStr

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.livebox5_control import MAX_REPLY_BYTES, ControlResult, change_schedule

MAC = "02:00:00:00:00:01"
MANAGEMENT = "02:00:00:00:00:02"
GATEWAY = "02:00:00:00:00:03"


class Lab:
    def __init__(self, mode: str = "normal", override: str = "") -> None:
        self.mode = mode
        self.override = override
        self.calls: list[str] = []
        self.writes = 0
        self.reads = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        self.calls.append(method)
        if payload["service"] == "sysbus.DeviceInfo":
            return httpx.Response(
                200,
                json={"status": {"ProductClass": "Livebox 5", "SoftwareVersion": "fixture"}},
            )
        if method == "createContext":
            return httpx.Response(200, json={"data": {"contextID": "fixture-context"}})
        assert payload["service"] == "sysbus.Scheduler"
        assert payload["parameters"]["ID"] == MAC
        if method == "overrideSchedule":
            self.writes += 1
            if self.mode != "mismatch":
                self.override = payload["parameters"]["override"]
            if self.mode == "timeout":
                raise httpx.ReadTimeout("private-transport-detail", request=request)
            if self.mode == "write-refused":
                return httpx.Response(403, text="private-response-detail")
            return httpx.Response(200, json={"status": True})
        assert method == "getSchedule"
        self.reads += 1
        if self.mode == "bad-readback" and self.reads == 2:
            return httpx.Response(200, json={"status": True, "data": {}})
        if self.mode == "missing":
            return httpx.Response(200, json={"status": False})
        if self.mode == "json":
            return httpx.Response(200, content=b"not-json")
        if self.mode == "oversized":
            return httpx.Response(200, content=b"x" * (MAX_REPLY_BYTES + 1))
        if self.mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://invalid.example"})
        value = "Disable" if self.override == "Disable" or self.mode == "scheduled" else "Enable"
        return httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "scheduleInfo": {"enable": True, "override": self.override, "value": value}
                },
            },
        )


def run(
    lab: Lab,
    *,
    blocked: bool = True,
    mac: str = MAC,
    address: str = "192.168.1.20",
    enabled: bool = True,
) -> ControlResult:
    return change_schedule(
        "https://192.168.1.1",
        [IPv4Network("192.168.1.0/24")],
        SecretStr("synthetic-password"),
        AccessRequest(RouterKind.LIVEBOX5, IPv4Address(address), mac, blocked),
        expected_firmware="fixture",
        management_mac=MANAGEMENT,
        gateway_mac=GATEWAY,
        enabled=enabled,
        confirmed=True,
        transport=httpx.MockTransport(lab.handle),
    )


@pytest.mark.parametrize("mode", ["timeout", "write-refused", "mismatch", "bad-readback"])
def test_attempted_write_failure_is_uncertain_and_never_retried(mode: str) -> None:
    lab = Lab(mode)
    with pytest.raises(AccessControlError, match="uncertain") as captured:
        run(lab)
    assert lab.writes == 1
    assert lab.calls.count("overrideSchedule") == 1
    assert "private-transport-detail" not in str(captured.value)
    assert "private-response-detail" not in str(captured.value)
    assert "synthetic-password" not in str(captured.value)
    if mode == "timeout":
        assert lab.override == "Disable"
        assert lab.reads == 1


@pytest.mark.parametrize("mode", ["missing", "json", "oversized", "redirect"])
def test_unknown_initial_state_never_writes(mode: str) -> None:
    lab = Lab(mode)
    with pytest.raises(AccessControlError):
        run(lab)
    assert lab.writes == 0
    assert lab.calls == ["get", "createContext", "getSchedule"]


@pytest.mark.parametrize("mac", [MANAGEMENT, GATEWAY])
def test_protected_devices_never_connect(mac: str) -> None:
    lab = Lab()
    with pytest.raises(AccessControlError, match="protected"):
        run(lab, mac=mac)
    assert lab.calls == []


@pytest.mark.parametrize("address", ["192.168.1.1", "192.168.2.20", "8.8.8.8"])
def test_router_or_out_of_scope_target_never_connects(address: str) -> None:
    lab = Lab()
    with pytest.raises(AccessControlError):
        run(lab, address=address)
    assert lab.calls == []


def test_disabled_control_never_connects() -> None:
    lab = Lab()
    with pytest.raises(AccessControlError):
        run(lab, enabled=False)
    assert lab.calls == []


def test_existing_forced_block_is_not_rewritten() -> None:
    lab = Lab(override="Disable")
    result = run(lab)
    assert result.changed is False
    assert result.state.blocked is True
    assert lab.writes == 0


def test_release_can_restore_a_schedule_that_still_blocks_access() -> None:
    lab = Lab("scheduled", override="Disable")
    result = run(lab, blocked=False)
    assert result.changed is True
    assert result.state.override == ""
    assert result.state.blocked is True
    assert lab.writes == 1


def test_release_without_override_preserves_parental_restriction() -> None:
    lab = Lab("scheduled")
    result = run(lab, blocked=False)
    assert result.changed is False
    assert result.state.blocked is True
    assert lab.writes == 0
