"""Bounded, process-local browser sessions; not yet wired into the dashboard."""

import math
import re
import secrets
import threading
import time
from collections.abc import Callable

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class SessionCapacityError(RuntimeError):
    """No live session is evicted to admit a new login."""


class SessionStore:
    """Absolute expiry, no persistence, no shared dashboard credential stored.

    Use one instance per single-process application. Restart invalidates sessions.
    The opaque value is a bearer secret: never log it or put it in a URL.
    """

    def __init__(
        self,
        *,
        ttl: float = 8 * 3600,
        capacity: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("session lifetime must be positive and finite")
        if type(capacity) is not int or capacity < 1:
            raise ValueError("session capacity must be a positive integer")
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._expires: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        """Call only after successful authentication and login CSRF checks."""
        with self._lock:
            now = self._clock()
            self._expires = {key: end for key, end in self._expires.items() if end > now}
            if len(self._expires) >= self._capacity:
                raise SessionCapacityError("session capacity reached")
            token = secrets.token_urlsafe(32)
            while token in self._expires:
                token = secrets.token_urlsafe(32)
            self._expires[token] = now + self._ttl
            return token

    def resolve(self, token: str | None) -> str | None:
        """Return the session binding only while valid; never extend its life."""
        if token is None or _TOKEN.fullmatch(token) is None:
            return None
        with self._lock:
            end = self._expires.get(token)
            if end is None:
                return None
            if self._clock() >= end:
                del self._expires[token]
                return None
            return token

    def revoke(self, token: str | None) -> None:
        """Invalidate one browser session, without affecting others."""
        if token is None:
            return
        with self._lock:
            self._expires.pop(token, None)
