"""Which stored events raise an alert, and how severe they are.

``to_confirm`` (random-MAC devices waiting for the owner) and ``online`` (a device came back)
never alert: a phone with a private MAC must not become noise that ends up ignored.
"""

from typing import Literal

from nettracker.db.repository import EventKind

Severity = Literal["info", "warning", "critical"]

SEVERITY: dict[EventKind, Severity] = {
    "new_device": "critical",
    "collector_stale": "critical",
    "offline": "warning",
    "latency_high": "warning",
    "merge_suggested": "info",
}

NOTIFIABLE_KINDS: tuple[EventKind, ...] = tuple(SEVERITY)
