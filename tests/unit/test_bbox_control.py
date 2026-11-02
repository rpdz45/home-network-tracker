"""Synthetic Bbox control port; no network traffic."""

from dataclasses import replace
from ipaddress import IPv4Address, IPv4Network

import pytest

from nettracker.routers.bbox_control import change_bbox_access
from nettracker.routers.bbox_session import BboxHost, BboxSnapshot
from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind

MAC = "02:00:00:00:00:20"


class Port:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.writes = 0
        self.host = BboxHost(7, None, "192.168.1.20", MAC, True, False)

    def snapshot(self) -> BboxSnapshot:
        return BboxSnapshot("synthetic-model", "synthetic-firmware", (self.host,), False)

    def set_blocked(self, identifier: int, *, blocked: bool) -> None:
        assert identifier == 7
        self.writes += 1
        if self.mode != "mismatch":
            self.host = replace(self.host, blocked=blocked)
        if self.mode == "timeout":
            raise TimeoutError("synthetic transport failure")


def run(port: Port, *, confirmed: bool = True) -> bool:
    result = change_bbox_access(
        AccessRequest(RouterKind.BBOX, IPv4Address("192.168.1.20"), MAC, True),
        port,
        [IPv4Network("192.168.1.0/24")],
        expected_model="synthetic-model",
        expected_firmware="synthetic-firmware",
        gateway_address=IPv4Address("192.168.1.1"),
        management_mac="02:00:00:00:00:02",
        gateway_mac="02:00:00:00:00:03",
        enabled=True,
        confirmed=confirmed,
    )
    return result.changed


def test_verified_and_idempotent() -> None:
    port = Port()
    assert run(port) is True
    assert run(port) is False
    assert port.writes == 1


@pytest.mark.parametrize("mode", ["timeout", "mismatch"])
def test_uncertain_never_retries(mode: str) -> None:
    port = Port(mode)
    with pytest.raises(AccessControlError, match="uncertain"):
        run(port)
    assert port.writes == 1


def test_confirmation_and_identity_precede_write() -> None:
    port = Port()
    with pytest.raises(AccessControlError):
        run(port, confirmed=False)
    port.host = replace(port.host, address="192.168.1.21")
    with pytest.raises(AccessControlError, match="identity"):
        run(port)
    assert port.writes == 0
