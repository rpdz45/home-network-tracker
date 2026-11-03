"""Server-owned action/result pairing with a synthetic executor only."""

from ipaddress import IPv4Address, IPv4Network

import pytest

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.routers.livebox5 import LiveboxError


def target(blocked: bool) -> AccessRequest:
    return AccessRequest(
        RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
    )


@pytest.mark.parametrize("blocked", [True, False])
def test_confirmed_request_matches_executed_action_and_cannot_replay(blocked: bool) -> None:
    calls: list[AccessRequest] = []
    result = object()

    def execute(request: AccessRequest) -> object:
        calls.append(request)
        return result

    guard = ControlGuards(
        lambda device, action: target(action),
        execute,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, blocked, session_id="owner")
    with pytest.raises(AccessControlError, match="session"):
        guard.confirm_with_request(pending.token, session_id="other")
    assert calls == []
    confirmed = guard.confirm_with_request(pending.token, session_id="owner")
    assert confirmed.request == pending.request == calls[0]
    assert confirmed.request.blocked is blocked
    assert confirmed.result is result
    with pytest.raises(AccessControlError):
        guard.confirm(pending.token, session_id="owner")
    assert len(calls) == 1
    next_pending = guard.prepare(1, blocked, session_id="owner")
    assert guard.confirm(next_pending.token, session_id="owner") is result
    with pytest.raises(AccessControlError):
        guard.confirm_with_request(next_pending.token, session_id="owner")
    assert len(calls) == 2


@pytest.mark.parametrize("error_type", [AccessControlError, LiveboxError, RuntimeError])
def test_failure_consumes_token_and_does_not_retry(error_type: type[Exception]) -> None:
    calls: list[AccessRequest] = []

    def execute(request: AccessRequest) -> None:
        calls.append(request)
        raise error_type("synthetic uncertain failure")

    guard = ControlGuards(
        lambda device, action: target(action),
        execute,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    pending = guard.prepare(1, True, session_id="owner")
    with pytest.raises(error_type, match="synthetic"):
        guard.confirm_with_request(pending.token, session_id="owner")
    with pytest.raises(AccessControlError, match="invalid"):
        guard.confirm_with_request(pending.token, session_id="owner")
    assert len(calls) == 1
    guard.prepare(1, False, session_id="owner")
