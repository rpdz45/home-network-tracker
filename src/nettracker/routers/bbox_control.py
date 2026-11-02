"""Bbox control orchestration only; no production write transport."""

from collections.abc import Sequence
from ipaddress import IPv4Address, IPv4Network
from typing import Protocol

from nettracker.routers.bbox_session import BboxHost, BboxSnapshot
from nettracker.routers.control import (
    PRIVATE_NETWORKS,
    AccessControlError,
    AccessRequest,
    AccessResult,
    RouterKind,
)


class BboxControlPort(Protocol):
    """Trusted adapter retaining one session; never a browser-supplied object."""

    def snapshot(self) -> BboxSnapshot: ...

    def set_blocked(self, identifier: int, *, blocked: bool) -> None: ...


def _target(snapshot: BboxSnapshot, request: AccessRequest) -> BboxHost:
    hosts = snapshot.hosts
    if len({host.identifier for host in hosts}) != len(hosts) or len(
        {host.mac.upper() for host in hosts}
    ) != len(hosts):
        raise AccessControlError("ambiguous Bbox inventory")
    matches = [host for host in hosts if host.mac.upper() == request.mac]
    if len(matches) != 1:
        raise AccessControlError("Bbox target is missing or ambiguous")
    host = matches[0]
    if (
        type(host.identifier) is not int
        or host.identifier < 0
        or host.address != str(request.address)
        or host.active is not True
        or type(host.blocked) is not bool
        or any(
            other.identifier != host.identifier and other.address == host.address for other in hosts
        )
    ):
        raise AccessControlError("Bbox target identity or rule state is unverified")
    return host


def change_bbox_access(
    request: AccessRequest,
    port: BboxControlPort,
    networks: Sequence[IPv4Network],
    *,
    expected_model: str,
    expected_firmware: str,
    gateway_address: IPv4Address,
    management_mac: str,
    gateway_mac: str,
    enabled: bool = False,
    confirmed: bool = False,
) -> AccessResult:
    """Require identity and read-back; never retry a failed write."""
    if enabled is not True or confirmed is not True or request.router != RouterKind.BBOX:
        raise AccessControlError("Bbox activation and confirmation are required")
    protected = {
        AccessRequest(RouterKind.BBOX, request.address, mac, False).mac
        for mac in (management_mac, gateway_mac)
    }
    if request.mac in protected or request.address == gateway_address:
        raise AccessControlError("management device and gateway are protected")
    if not any(request.address in n for n in PRIVATE_NETWORKS) or not any(
        request.address in n for n in networks
    ):
        raise AccessControlError("target is outside allowed private subnets")
    if not expected_model or not expected_firmware:
        raise AccessControlError("exact Bbox model and firmware are required")
    before = port.snapshot()
    if before.model != expected_model or before.firmware != expected_firmware:
        raise AccessControlError("Bbox model or firmware mismatch")
    target = _target(before, request)
    if target.blocked is request.blocked:
        return AccessResult(request.mac, request.blocked, False)
    try:
        port.set_blocked(target.identifier, blocked=request.blocked)
        after = port.snapshot()
        observed = _target(after, request)
        if (
            after.model != before.model
            or after.firmware != before.firmware
            or observed.identifier != target.identifier
            or observed.blocked is not request.blocked
        ):
            raise AccessControlError("Bbox read-back mismatch")
    except Exception:
        raise AccessControlError("Bbox outcome is uncertain; do not retry automatically") from None
    return AccessResult(request.mac, request.blocked, True)
