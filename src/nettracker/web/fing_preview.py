"""Bounded server-side previews; browser input never supplies inventory contents."""

import secrets
from collections.abc import Callable
from threading import Lock
from time import monotonic

from nettracker.db.identifications import MAX_PREVIEW_AGE_SECONDS, IdentificationError
from nettracker.discovery.fing import FingInventory


class FingPreviewStore:
    """Keep at most one preview per application process, with a one-time token.

    This is not authentication or CSRF protection. Callers must enforce both
    before consuming a preview. Restarting a worker discards its preview.
    Storage independently validates the inventory retrieval timestamp.
    """

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._inventory: FingInventory | None = None
        self._token: str | None = None
        self._created = 0.0

    def replace(self, inventory: FingInventory) -> str:
        """Invalidate the previous token and retain only this server-side result."""
        with self._lock:
            self._inventory = inventory
            token = secrets.token_hex(32)
            self._token = token
            self._created = self._clock()
            return token

    def clear(self) -> None:
        """Discard any preview, for example before starting another API read."""
        with self._lock:
            self._inventory = None
            self._token = None

    def consume(self, token: str) -> FingInventory:
        """Atomically consume a matching fresh preview; refuse retries and replay."""
        with self._lock:
            age = self._clock() - self._created
            if not 0 <= age <= MAX_PREVIEW_AGE_SECONDS:
                self._inventory = None
                self._token = None
            if (
                self._inventory is None
                or self._token is None
                or len(token) != 64
                or not token.isascii()
                or not secrets.compare_digest(self._token, token)
            ):
                raise IdentificationError("invalid or expired identification preview")
            inventory = self._inventory
            self._inventory = None
            self._token = None
            return inventory
