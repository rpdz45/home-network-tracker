"""Revalidate browser sessions before delegating to process-local control guards."""

from typing import Generic, TypeVar

from nettracker.routers.control import AccessControlError
from nettracker.routers.control_guards import ConfirmedControl, ControlGuards, PendingControl
from nettracker.web.sessions import SessionStore

Result = TypeVar("Result")


class SessionBoundControl(Generic[Result]):
    """Share the authentication store and a trusted guard; no HTTP routes here.

    Credentials, inventory resolvers and executors must never come from forms.
    Session validation is a point-in-time check, not an atomic transaction with
    logout or expiry. Revocation cannot cancel an operation already admitted.
    """

    def __init__(
        self,
        sessions: SessionStore,
        guard: ControlGuards[Result],
        *,
        enabled: bool = False,
    ) -> None:
        self._sessions = sessions
        self._guard = guard
        self._enabled = enabled

    def _session(self, cookie: str | None) -> str:
        if self._enabled is not True:
            raise AccessControlError("browser control is disabled")
        session = self._sessions.resolve(cookie)
        if session is None:
            raise AccessControlError("a valid browser session is required")
        return session

    def prepare(self, device_id: int, blocked: bool, *, cookie: str | None) -> PendingControl:
        """Resolve the target without executing, bound to a currently valid session."""
        session = self._session(cookie)
        return self._guard.prepare(device_id, blocked, session_id=session)

    def confirm(self, token: str, *, cookie: str | None) -> Result:
        """Revalidate, then consume once through the guard; never retry execution."""
        session = self._session(cookie)
        return self._guard.confirm(token, session_id=session)

    def confirm_with_request(self, token: str, *, cookie: str | None) -> ConfirmedControl[Result]:
        """Revalidate the session before returning the confirmed request and result."""
        session = self._session(cookie)
        return self._guard.confirm_with_request(token, session_id=session)
