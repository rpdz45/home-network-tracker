"""Synthetic authenticated control exchanges; no real network requests."""

import json
from ipaddress import IPv4Address, IPv4Network

import httpx
import pytest
from pydantic import SecretStr

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.livebox5_control import change_schedule

MAC = "02:00:00:00:00:01"
NETWORKS = [IPv4Network("192.168.1.0/24")]


def run(
    transport: httpx.MockTransport, *, blocked: bool = True, confirmed: bool = True
) -> object:
    return change_schedule(
        "https://192.168.1.1",
        NETWORKS,
        SecretStr("synthetic-test-password"),
        AccessRequest(RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), MAC, blocked),
        expected_firmware="synthetic-firmware",
        management_mac="02:00:00:00:00:02",
        gateway_mac="02:00:00:00:00:03",
        enabled=True,
        confirmed=confirmed,
        transport=transport,
    )


@pytest.mark.parametrize("blocked", [True, False])
def test_one_write_and_readback_preserve_schedule(blocked: bool) -> None:
    calls: list[str] = []
    override = "" if blocked else "Disable"

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal override
        payload = json.loads(request.content)
        method = payload["method"]
        calls.append(method)
        if payload["service"] == "sysbus.DeviceInfo":
            reply = {"status": {"ProductClass": "Livebox 5", "SoftwareVersion": "synthetic-firmware"}}
        elif method == "createContext":
            reply = {"data": {"contextID": "test-context"}}
        else:
            assert request.headers["X-Context"] == "test-context"
            assert payload["parameters"]["ID"] == MAC
            if method == "overrideSchedule":
                override = payload["parameters"]["override"]
                assert override == ("Disable" if blocked else "")
                return httpx.Response(200, json={"status": True})
            reply = {
                "status": True,
                "data": {
                    "scheduleInfo": {
                        "enable": True,
                        "override": override,
                        "value": "Disable" if override == "Disable" else "Enable",
                    }
                },
            }
        return httpx.Response(200, json=reply)

    result = run(httpx.MockTransport(handle), blocked=blocked)
    assert getattr(result, "changed") is True
    assert calls == ["get", "createContext", "getSchedule", "overrideSchedule", "getSchedule"]


def test_unconfirmed_never_connects() -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("unconfirmed action must not connect")

    with pytest.raises(AccessControlError):
        run(httpx.MockTransport(forbidden), confirmed=False)


def test_firmware_mismatch_precedes_password() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert b"synthetic-test-password" not in request.content
        return httpx.Response(200, json={"status": {"ProductClass": "Livebox 5"}})

    with pytest.raises(AccessControlError, match="firmware"):
        run(httpx.MockTransport(handle))
    assert len(calls) == 1
