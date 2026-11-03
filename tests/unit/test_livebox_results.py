"""Synthetic result contracts; no credentials, database, HTTP transport or box."""

import pytest
from fastapi import HTTPException

from nettracker.routers.control import AccessControlError
from nettracker.routers.livebox5 import LiveboxError
from nettracker.routers.livebox5_access import ScheduleState
from nettracker.routers.livebox5_control import ControlResult
from nettracker.web.livebox_results import (
    FAILURE_DETAIL,
    confirmed_result_view,
    describe_control_result,
)


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize(
    ("blocked", "override", "value", "expected"),
    [
        (True, "Disable", "Disable", "Forçage de blocage présent"),
        (False, "", "Disable", "Aucun forçage ; calendrier lu : accès désactivé."),
        (False, "", "Enable", "Aucun forçage ; calendrier lu : accès activé."),
    ],
)
def test_result_distinguishes_change_and_schedule(
    changed: bool, blocked: bool, override: str, value: str, expected: str
) -> None:
    result = ControlResult(changed, ScheduleState(override, value))
    view = describe_control_result(result, blocked=blocked)
    assert expected in view.schedule
    assert (view.change == "Modification effectuée") is changed
    assert "ne prouve pas" in view.warning
    assert "Internet" in view.warning


@pytest.mark.parametrize(
    ("result", "blocked"),
    [
        (None, True),
        (object(), False),
        (ControlResult(True, ScheduleState("", "Enable")), True),
        (ControlResult(True, ScheduleState("Disable", "Enable")), True),
        (ControlResult(False, ScheduleState("Disable", "Disable")), False),
        (ControlResult(True, ScheduleState("", "unknown")), False),
    ],
)
def test_invalid_or_mismatched_result_is_not_success(result: object, blocked: bool) -> None:
    with pytest.raises(AccessControlError):
        describe_control_result(result, blocked=blocked)


@pytest.mark.parametrize("error_type", [AccessControlError, LiveboxError])
def test_expected_errors_are_redacted_and_operation_is_not_retried(
    error_type: type[Exception],
) -> None:
    calls: list[str] = []

    def operation() -> ControlResult:
        calls.append("called")
        raise error_type("synthetic-sensitive-adapter-detail")

    with pytest.raises(HTTPException) as caught:
        confirmed_result_view(operation, blocked=True)
    assert caught.value.status_code == 409
    assert caught.value.detail == FAILURE_DETAIL
    assert "synthetic-sensitive" not in str(caught.value.detail)
    assert calls == ["called"]


def test_incoherent_return_uses_same_failure_boundary() -> None:
    calls: list[str] = []

    def operation() -> ControlResult:
        calls.append("called")
        return ControlResult(True, ScheduleState("", "Enable"))

    with pytest.raises(HTTPException) as caught:
        confirmed_result_view(operation, blocked=True)
    assert caught.value.status_code == 409
    assert caught.value.detail == FAILURE_DETAIL
    assert calls == ["called"]


def test_success_operation_is_invoked_once() -> None:
    calls: list[str] = []

    def operation() -> ControlResult:
        calls.append("called")
        return ControlResult(False, ScheduleState("", "Disable"))

    view = confirmed_result_view(operation, blocked=False)
    assert "sans modification" in view.change
    assert "accès désactivé" in view.schedule
    assert calls == ["called"]
