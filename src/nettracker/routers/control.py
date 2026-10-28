"""Explicit, verified access-rule changes through an injected router adapter.

No production adapter, HTTP client, credential handling or automatic blocking lives here.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from typing import Protocol

PRIVATE_NETWORKS = tuple(
    IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class RouterKind(StrEnum):
    LIVEBOX5 = "livebox5"
    BBOX = "bbox"


class AccessControlError(Exception):
    """An access-rule request was refused or could not be verified."""


@dataclass(frozen=True)
class AccessRequest:
    router: RouterKind
    address: IPv4Address
    mac: str
    blocked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.router, RouterKind) or not isinstance(self.address, IPv4Address):
            raise ValueError("a supported router kind and IPv4 address are required")
        if type(self.blocked) is not bool:
            raise ValueError("blocked must be a boolean")
        if (
            not isinstance(self.mac, str)
            or re.fullmatch(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", self.mac) is None
        ):
            raise ValueError("invalid device MAC address")
        octets = bytes.fromhex(self.mac.replace(":", ""))
        if octets[0] & 1 or not any(octets):
            raise ValueError("a nonzero unicast MAC address is required")
        object.__setattr__(self, "mac", self.mac.upper())


@dataclass(frozen=True)
class AccessResult:
    mac: str
    blocked: bool
    changed: bool


class AccessController(Protocol):
    """Adapters report rule state, not proof of Internet connectivity.

    Implementations must authenticate, enforce their own model/firmware support,
    preserve unrelated rules, avoid implicit retries and sanitize transport errors.
    """

    @property
    def kind(self) -> RouterKind: ...

    def read_blocked(self, mac: str) -> bool | None: ...

    def set_blocked(self, mac: str, *, blocked: bool) -> None: ...


def change_access(
    request: AccessRequest,
    controller: AccessController,
    allowed_subnets: Sequence[IPv4Network],
    *,
    enabled: bool = False,
    confirmed: bool = False,
) -> AccessResult:
    """Apply one explicit rule change and require a matching read-back.

    The flags are application interlocks, not authentication or CSRF protection.
    A future web route must enforce both before calling this service.
    """
    if enabled is not True or confirmed is not True:
        raise AccessControlError("access control requires activation and confirmation")
    if not any(request.address in network for network in PRIVATE_NETWORKS) or not any(
        request.address in network for network in allowed_subnets
    ):
        raise AccessControlError("device is outside allowed private subnets")
    if controller.kind != request.router:
        raise AccessControlError("router adapter does not match the request")
    previous = controller.read_blocked(request.mac)
    if type(previous) is not bool:
        raise AccessControlError("current access rule is unknown; no change was attempted")
    if previous is request.blocked:
        return AccessResult(request.mac, request.blocked, changed=False)
    controller.set_blocked(request.mac, blocked=request.blocked)
    observed = controller.read_blocked(request.mac)
    if observed is not request.blocked:
        raise AccessControlError("access rule change is unverified; do not assume success")
    return AccessResult(request.mac, request.blocked, changed=True)
