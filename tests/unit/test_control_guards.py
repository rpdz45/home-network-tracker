"""Synthetic inventory and executor only; no network traffic."""

from ipaddress import IPv4Address, IPv4Network

import pytest

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards


def target(blocked: bool = True, address: str = "192.168.1.20") -> AccessRequest:
    return AccessRequest(RouterKind.LIVEBOX5, IPv4Address(address), "02:00:00:00:00:20", blocked)


def test_single_use_and_session_binding() -> None:
    calls: list[AccessRequest] = []
    guard = ControlGuards(
        lambda device, blocked: target(blocked),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, True, session_id="owner")
    assert calls == []
    with pytest.raises(AccessControlError, match="session"):
        guard.confirm(pending.token, session_id="other")
    guard.confirm(pending.token, session_id="owner")
    assert calls == [target()]
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")


def test_changed_inventory_consumes_confirmation() -> None:
    inventory = [target()]
    calls: list[AccessRequest] = []
    guard = ControlGuards(
        lambda device, blocked: inventory[0],
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, True, session_id="owner")
    inventory[0] = target(address="192.168.1.21")
    with pytest.raises(AccessControlError, match="target changed"):
        guard.confirm(pending.token, session_id="owner")
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")
    assert calls == []


def test_expiry_capacity_and_cleanup() -> None:
    now = [0.0]
    calls: list[AccessRequest] = []
    guard = ControlGuards(
        lambda device, blocked: target(blocked),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
        capacity=1,
        clock=lambda: now[0],
    )
    pending = guard.prepare(1, True, session_id="owner")
    with pytest.raises(AccessControlError, match="capacity"):
        guard.prepare(1, False, session_id="owner")
    now[0] = 60.0
    with pytest.raises(AccessControlError, match="expired"):
        guard.confirm(pending.token, session_id="owner")
    guard.prepare(1, False, session_id="owner")
    assert calls == []


@pytest.mark.parametrize(
    ("enabled", "address", "protected"),
    [
        (False, "192.168.1.20", "02:00:00:00:00:01"),
        (True, "192.168.1.20", "02:00:00:00:00:20"),
        (True, "192.168.2.20", "02:00:00:00:00:01"),
        (True, "8.8.8.8", "02:00:00:00:00:01"),
    ],
)
def test_refused_targets(enabled: bool, address: str, protected: str) -> None:
    calls: list[AccessRequest] = []
    guard = ControlGuards(
        lambda device, blocked: target(blocked, address),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        [protected],
        enabled=enabled,
    )
    with pytest.raises(AccessControlError):
        guard.prepare(1, True, session_id="owner")
    assert calls == []


def test_failure_consumes_token_and_releases_lock() -> None:
    def fail(request: AccessRequest) -> None:
        raise AccessControlError("uncertain outcome")

    guard = ControlGuards(
        lambda device, blocked: target(blocked),
        fail,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, True, session_id="owner")
    with pytest.raises(AccessControlError, match="uncertain"):
        guard.confirm(pending.token, session_id="owner")
    with pytest.raises(AccessControlError, match="invalid"):
        guard.confirm(pending.token, session_id="owner")
    guard.prepare(1, True, session_id="owner")


def test_executor_cannot_reenter_service() -> None:
    def execute(request: AccessRequest) -> None:
        with pytest.raises(AccessControlError, match="in progress"):
            guard.prepare(1, False, session_id="owner")

    guard = ControlGuards(
        lambda device, blocked: target(blocked),
        execute,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, True, session_id="owner")
    guard.confirm(pending.token, session_id="owner")
