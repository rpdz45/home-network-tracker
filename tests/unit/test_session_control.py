"""Actual session/guard composition with synthetic inventory and executor only."""

from ipaddress import IPv4Address, IPv4Network

import pytest

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.session_control import SessionBoundControl
from nettracker.web.sessions import SessionStore


def target(blocked: bool = True) -> AccessRequest:
    return AccessRequest(
        RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
    )


def setup_control(
    *, enabled: bool = True, ttl: float = 3600
) -> tuple[SessionStore, SessionBoundControl[None], list[AccessRequest], list[float]]:
    now = [0.0]
    calls: list[AccessRequest] = []
    sessions = SessionStore(ttl=ttl, clock=lambda: now[0])
    guard = ControlGuards[None](
        lambda device, blocked: target(blocked),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
        clock=lambda: now[0],
    )
    control = SessionBoundControl(sessions, guard, enabled=enabled)
    return sessions, control, calls, now


def test_distinct_sessions_single_execution_and_replay_refusal() -> None:
    sessions, control, calls, _ = setup_control()
    first, second = sessions.issue(), sessions.issue()
    pending = control.prepare(1, True, cookie=first)
    assert pending.request == target()
    assert calls == []
    with pytest.raises(AccessControlError, match="session"):
        control.confirm(pending.token, cookie=second)
    assert calls == []
    control.confirm(pending.token, cookie=first)
    assert calls == [target()]
    with pytest.raises(AccessControlError):
        control.confirm(pending.token, cookie=first)
    assert calls == [target()]


def test_revoked_session_and_new_login_cannot_confirm_old_token() -> None:
    sessions, control, calls, _ = setup_control()
    first = sessions.issue()
    pending = control.prepare(1, True, cookie=first)
    sessions.revoke(first)
    with pytest.raises(AccessControlError, match="valid browser session"):
        control.confirm(pending.token, cookie=first)
    replacement = sessions.issue()
    with pytest.raises(AccessControlError, match="session"):
        control.confirm(pending.token, cookie=replacement)
    assert calls == []


def test_session_expiry_precedes_unexpired_confirmation() -> None:
    sessions, control, calls, now = setup_control(ttl=10)
    cookie = sessions.issue()
    pending = control.prepare(1, True, cookie=cookie)
    now[0] = 10
    with pytest.raises(AccessControlError, match="valid browser session"):
        control.confirm(pending.token, cookie=cookie)
    assert calls == []


def test_confirmation_expiry_with_live_session() -> None:
    sessions, control, calls, now = setup_control()
    cookie = sessions.issue()
    pending = control.prepare(1, True, cookie=cookie)
    now[0] = 60
    assert sessions.resolve(cookie) == cookie
    with pytest.raises(AccessControlError, match="expired"):
        control.confirm(pending.token, cookie=cookie)
    assert calls == []


@pytest.mark.parametrize("cookie", [None, "", "shared-dashboard-credential", "a" * 43])
def test_unknown_cookie_never_reaches_executor(cookie: str | None) -> None:
    _, control, calls, _ = setup_control()
    with pytest.raises(AccessControlError, match="valid browser session"):
        control.prepare(1, True, cookie=cookie)
    with pytest.raises(AccessControlError, match="valid browser session"):
        control.confirm("unknown-confirmation", cookie=cookie)
    assert calls == []


def test_disabled_switch_prevents_preparation_and_confirmation() -> None:
    sessions, control, calls, _ = setup_control(enabled=False)
    cookie = sessions.issue()
    with pytest.raises(AccessControlError, match="disabled"):
        control.prepare(1, True, cookie=cookie)
    with pytest.raises(AccessControlError, match="disabled"):
        control.confirm("unknown-confirmation", cookie=cookie)
    assert calls == []


def test_default_is_disabled_even_with_enabled_guard() -> None:
    sessions = SessionStore()
    calls: list[AccessRequest] = []
    guard = ControlGuards[None](
        lambda device, blocked: target(blocked),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    control = SessionBoundControl(sessions, guard)
    with pytest.raises(AccessControlError, match="disabled"):
        control.prepare(1, True, cookie=sessions.issue())
    assert calls == []
