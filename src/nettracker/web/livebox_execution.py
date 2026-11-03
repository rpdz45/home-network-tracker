"""Session-bound Livebox result validation; no adapter construction or retry."""

from typing import TypeVar

from fastapi import HTTPException

from nettracker.routers.control import AccessControlError, RouterKind
from nettracker.routers.livebox5 import LiveboxError
from nettracker.web.livebox_results import (
    FAILURE_DETAIL,
    ControlResultView,
    describe_control_result,
)
from nettracker.web.session_control import SessionBoundControl

Result = TypeVar("Result")


def confirm_livebox_result(
    control: SessionBoundControl[Result], token: str, *, cookie: str | None
) -> ControlResultView:
    """Confirm once and validate using the request returned by the trusted guard.

    The caller must still enforce HTTP authentication, CSRF and explicit consent.
    The injected resolver/executor must enforce Livebox targeting before effects.
    This function does not install routes or grant Internet-access guarantees.
    """
    try:
        confirmed = control.confirm_with_request(token, cookie=cookie)
        if confirmed.request.router != RouterKind.LIVEBOX5:
            raise AccessControlError("a Livebox result is required")
        return describe_control_result(confirmed.result, blocked=confirmed.request.blocked)
    except (AccessControlError, LiveboxError):
        raise HTTPException(409, FAILURE_DETAIL) from None
