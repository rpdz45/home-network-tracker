"""Actual session/guard composition with synthetic execution only."""

from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network

import pytest
from fastapi import HTTPException

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.routers.livebox5 import LiveboxError
from nettracker.routers.livebox5_access import ScheduleState
from nettracker.routers.livebox5_control import ControlResult
from nettracker.web.livebox_execution import confirm_livebox_result
from nettracker.web.livebox_results import FAILURE_DETAIL
from nettracker.web.session_control import SessionBoundControl
from nettracker.web.sessions import SessionStore


def setup_control(
    execute: Callable[[AccessRequest], object], *, enabled: bool = True
) -> tuple[SessionStore, SessionBoundControl[object], list[float]]:
    now = [0.0]
    sessions = SessionStore(ttl=10, clock=lambda: now[0])
    guard = ControlGuards[object](
        lambda device, blocked: AccessRequest(
            RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
        ),
        execute,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
        clock=lambda: now[0],
    )
    return sessions, SessionBoundControl(sessions, guard, enabled=enabled), now


@pytest.mark.parametrize(
    ("blocked", "override", "value"),
    [(True, "Disable", "Disable"), (False, "", "Enable"), (False, "", "Disable")],
)
@pytest.mark.parametrize("changed", [True, False])
def test_confirmed_action_drives_result_description(
    blocked: bool, override: str, value: str, changed: bool
) -> None:
    calls: list[AccessRequest] = []

    def execute(request: AccessRequest) -> object:
        calls.append(request)
        return ControlResult(changed, ScheduleState(override, value))

    sessions, control, _ = setup_control(execute)
    cookie = sessions.issue()
    pending = control.prepare(1, blocked, cookie=cookie)
    view = confirm_livebox_result(control, pending.token, cookie=cookie)
    assert len(calls) == 1
    assert calls[0] == pending.request
    assert calls[0].blocked is blocked
    assert view.change == (
        "Modification effectuée" if changed else "Etat déjà conforme, sans modification"
    )
    assert ("accès désactivé" if value == "Disable" else "accès activé") in view.schedule
    assert ("Forçage de blocage présent" if blocked else "Aucun forçage") in view.schedule
    assert "ne prouve pas l'accès Internet effectif" in view.warning
    with pytest.raises(HTTPException) as replay:
        confirm_livebox_result(control, pending.token, cookie=cookie)
    assert replay.value.status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize("error_type", [AccessControlError, LiveboxError])
def test_known_failure_is_masked_consumed_and_never_retried(error_type: type[Exception]) -> None:
    calls: list[AccessRequest] = []

    def execute(request: AccessRequest) -> object:
        calls.append(request)
        raise error_type("synthetic-private-detail")

    sessions, control, _ = setup_control(execute)
    cookie = sessions.issue()
    pending = control.prepare(1, True, cookie=cookie)
    for _ in range(2):
        with pytest.raises(HTTPException) as failure:
            confirm_livebox_result(control, pending.token, cookie=cookie)
        assert failure.value.status_code == 409
        assert failure.value.detail == FAILURE_DETAIL
        assert "synthetic-private-detail" not in str(failure.value.detail)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "result", [None, ControlResult(True, ScheduleState("", "Enable"))]
)
def test_invalid_or_inconsistent_result_cannot_be_presented_as_success(result: object) -> None:
    calls: list[AccessRequest] = []

    def execute(request: AccessRequest) -> object:
        calls.append(request)
        return result

    sessions, control, _ = setup_control(execute)
    cookie = sessions.issue()
    pending = control.prepare(1, True, cookie=cookie)
    for _ in range(2):
        with pytest.raises(HTTPException) as failure:
            confirm_livebox_result(control, pending.token, cookie=cookie)
        assert failure.value.status_code == 409
        assert failure.value.detail == FAILURE_DETAIL
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["missing", "other", "revoked", "expired", "disabled"])
def test_session_checks_precede_execution(mode: str) -> None:
    calls: list[AccessRequest] = []
    sessions, control, now = setup_control(calls.append)
    owner = sessions.issue()
    pending = control.prepare(1, True, cookie=owner)
    cookie: str | None = owner
    if mode == "missing":
        cookie = None
    elif mode == "other":
        cookie = sessions.issue()
    elif mode == "revoked":
        sessions.revoke(owner)
    elif mode == "expired":
        now[0] = 10
    else:
        disabled_sessions, disabled, _ = setup_control(calls.append, enabled=False)
        with pytest.raises(HTTPException) as failure:
            confirm_livebox_result(disabled, pending.token, cookie=disabled_sessions.issue())
        assert failure.value.status_code == 409
        assert calls == []
        return
    with pytest.raises(HTTPException) as failure:
        confirm_livebox_result(control, pending.token, cookie=cookie)
    assert failure.value.status_code == 409
    assert calls == []
    if mode in {"missing", "other"}:
        confirmed = control.confirm_with_request(pending.token, cookie=owner)
        assert confirmed.request == pending.request
        assert confirmed.result is None
        assert len(calls) == 1


def test_unexpected_failure_propagates_but_token_is_consumed() -> None:
    calls: list[AccessRequest] = []

    def execute(request: AccessRequest) -> object:
        calls.append(request)
        raise RuntimeError("synthetic bug")

    sessions, control, _ = setup_control(execute)
    cookie = sessions.issue()
    pending = control.prepare(1, True, cookie=cookie)
    with pytest.raises(RuntimeError, match="synthetic bug"):
        confirm_livebox_result(control, pending.token, cookie=cookie)
    with pytest.raises(HTTPException):
        confirm_livebox_result(control, pending.token, cookie=cookie)
    assert len(calls) == 1
