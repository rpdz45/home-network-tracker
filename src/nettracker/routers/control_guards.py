"""Process-local control interlocks; no HTTP routes or network access."""

import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import Generic, TypeVar

from nettracker.routers.control import PRIVATE_NETWORKS, AccessControlError, AccessRequest

Result = TypeVar("Result")


@dataclass(frozen=True)
class PendingControl:
    token: str
    device_id: int
    request: AccessRequest
    expires_at: float


@dataclass(frozen=True)
class _Entry:
    pending: PendingControl
    session_id: str


class ControlGuards(Generic[Result]):
    """Share one instance across requests in a single-process application.

    The resolver must read trusted local inventory, reject merged, stale or
    ambiguous devices and return a canonical request. The executor must retain
    adapter-level protections and read-back verification. Neither is web input.
    """

    def __init__(
        self,
        resolve: Callable[[int, bool], AccessRequest],
        execute: Callable[[AccessRequest], Result],
        networks: Sequence[IPv4Network],
        protected_macs: Sequence[str],
        *,
        enabled: bool = False,
        ttl: float = 60.0,
        capacity: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < ttl <= 300 or capacity < 1:
            raise ValueError("invalid confirmation lifetime or capacity")
        if not networks or not protected_macs:
            raise ValueError("explicit networks and protected MACs are required")
        self._resolve = resolve
        self._execute = execute
        self._networks = tuple(networks)
        self._protected = frozenset(mac.upper() for mac in protected_macs)
        self._enabled = enabled
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._pending: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _target(self, device_id: int, blocked: bool) -> AccessRequest:
        if self._enabled is not True:
            raise AccessControlError("access control is disabled")
        if type(device_id) is not int or device_id < 1 or type(blocked) is not bool:
            raise AccessControlError("invalid device or action")
        request = self._resolve(device_id, blocked)
        if request.blocked is not blocked:
            raise AccessControlError("inventory resolver returned a different action")
        if request.mac in self._protected:
            raise AccessControlError("protected device cannot be targeted")
        if not any(request.address in n for n in PRIVATE_NETWORKS) or not any(
            request.address in n for n in self._networks
        ):
            raise AccessControlError("target is outside allowed private subnets")
        return request

    def prepare(self, device_id: int, blocked: bool, *, session_id: str) -> PendingControl:
        """Resolve server-side and issue an expiring confirmation, without execution."""
        if not session_id:
            raise AccessControlError("an authenticated session binding is required")
        if not self._lock.acquire(blocking=False):
            raise AccessControlError("another control operation is in progress")
        try:
            request = self._target(device_id, blocked)
            now = self._clock()
            self._pending = {
                token: entry
                for token, entry in self._pending.items()
                if entry.pending.expires_at > now
            }
            if len(self._pending) >= self._capacity:
                raise AccessControlError("confirmation capacity reached")
            pending = PendingControl(
                secrets.token_urlsafe(32), device_id, request, now + self._ttl
            )
            self._pending[pending.token] = _Entry(pending, session_id)
            return pending
        finally:
            self._lock.release()

    def confirm(self, token: str, *, session_id: str) -> Result:
        """Consume before execution, including uncertain failures; never retry here."""
        if not self._lock.acquire(blocking=False):
            raise AccessControlError("another control operation is in progress")
        try:
            entry = self._pending.get(token)
            if entry is None or not session_id or entry.session_id != session_id:
                raise AccessControlError("confirmation is invalid for this session")
            del self._pending[token]
            pending = entry.pending
            if self._clock() >= pending.expires_at:
                raise AccessControlError("confirmation has expired")
            current = self._target(pending.device_id, pending.request.blocked)
            if current != pending.request:
                raise AccessControlError("target changed; a new confirmation is required")
            return self._execute(current)
        finally:
            self._lock.release()
