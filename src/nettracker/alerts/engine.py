"""Turn stored events into notification records, with anti-spam and a dry-run default.

No network access lives here: real senders are injected as ``Notifier`` objects.
"""

import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from nettracker.alerts.latency import detect_high_latency
from nettracker.alerts.rules import SEVERITY, Severity
from nettracker.config import AlertSettings
from nettracker.db.repository import EventKind, Repository, to_iso
from nettracker.errors import ConfigError, DatabaseError, NetTrackerError

logger = logging.getLogger(__name__)

DRY_RUN_CHANNEL = "dry-run"
ALL_CHANNELS = "all"

# The kind list must match NOTIFIABLE_KINDS (checked by a test). An ``offline`` event only
# becomes pending once it is older than ``alerts.offline_after_minutes``.
_PENDING_SQL = (
    "SELECT e.id, e.device_id, e.kind, e.details, e.created_at FROM events e "
    "LEFT JOIN notifications n ON n.event_id = e.id "
    "WHERE n.id IS NULL AND e.kind IN "
    "('new_device', 'offline', 'latency_high', 'collector_stale', 'merge_suggested') "
    "AND (e.kind != 'offline' OR e.created_at <= ?) "
    "ORDER BY e.id LIMIT ?"
)
# Only delivered (or dry-run) alerts start a cooldown: suppressed and failed ones do not.
_RECENT_SQL = (
    "SELECT 1 FROM events p JOIN notifications n ON n.event_id = p.id "
    "WHERE p.kind = ? AND p.device_id IS ? AND p.id < ? AND p.created_at >= ? "
    "AND n.status IN ('sent', 'dry_run') LIMIT 1"
)
_RECOVERED_SQL = (
    "SELECT 1 FROM events o WHERE o.kind = 'online' AND o.device_id = ? AND o.id > ? LIMIT 1"
)
_DEVICE_SQL = "SELECT alias, hostname, mac FROM devices WHERE id = ?"

_TEXTS: dict[str, str] = {
    "new_device": "Nouvel appareil détecté : {label}",
    "offline": "Aucune réponse ICMP : {label}",
    "latency_high": "Latence élevée : {label} (moyenne {average_ms} ms)",
    "collector_stale": "Le collecteur n'a plus de scan réussi (dernier : {last_success})",
    "merge_suggested": "Fusion possible à valider à la main : {label}",
}


class NotifierError(NetTrackerError):
    """A notifier could not deliver a message. Never put secrets in its text."""


@dataclass(frozen=True)
class AlertMessage:
    event_id: int
    kind: EventKind
    severity: Severity
    text: str


class Notifier(Protocol):
    """A delivery channel. ``send`` must raise ``NotifierError`` on failure."""

    name: str

    def send(self, message: AlertMessage) -> None: ...


@dataclass(frozen=True)
class AlertRunSummary:
    processed: int
    sent: int
    dry_run: int
    suppressed: int
    failed: int
    latency_events: int


def _fetch(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot read alert data: {exc}") from exc


def _label(conn: sqlite3.Connection, device_id: int | None) -> str:
    if device_id is None:
        return "appareil non identifié"
    rows = _fetch(conn, _DEVICE_SQL, (device_id,))
    if not rows:
        return f"appareil #{device_id}"
    alias, hostname, mac = rows[0]
    return f"{alias or hostname or 'sans nom'} ({mac})"


def _build_message(
    conn: sqlite3.Connection,
    event_id: int,
    device_id: int | None,
    kind: EventKind,
    raw_details: str | None,
) -> AlertMessage:
    try:
        details = json.loads(raw_details) if raw_details else {}
    except ValueError:
        details = {}
    values = {"last_success": "inconnu", "average_ms": "?"}
    if isinstance(details, dict):
        values["last_success"] = str(details.get("last_success_at", "inconnu"))
        values["average_ms"] = str(details.get("average_ms", "?"))
    text = _TEXTS[kind].format(label=_label(conn, device_id), **values)
    return AlertMessage(event_id, kind, SEVERITY[kind], text)


def _suppression_reason(conn: sqlite3.Connection, row: Any, cooldown: timedelta) -> str | None:
    """Return why a pending event must not alert (``recovered`` or ``cooldown``), if any."""
    event_id, device_id, kind, _, created_at = row
    if kind == "offline" and _fetch(conn, _RECOVERED_SQL, (device_id, event_id)):
        return "recovered"
    cutoff = to_iso(datetime.fromisoformat(created_at) - cooldown)
    if _fetch(conn, _RECENT_SQL, (kind, device_id, event_id, cutoff)):
        return "cooldown"
    return None


def process_pending_events(
    conn: sqlite3.Connection,
    settings: AlertSettings,
    now: datetime,
    notifiers: Sequence[Notifier] = (),
) -> AlertRunSummary:
    """Detect sustained latency, then record a notification row for each pending event.

    Events are handled oldest first and bounded per run. In dry-run (the default) nothing is
    sent and notifiers are never called. A failed delivery is recorded and not retried in this
    version. The next run skips events already recorded.
    """
    to_iso(now)
    if not settings.dry_run and not notifiers:
        raise ConfigError("alerts.dry_run=false requires at least one notifier; none is configured")
    repo = Repository(conn)
    latency_events = detect_high_latency(conn, now, settings.latency_high_ms)
    cooldown = timedelta(minutes=settings.cooldown_minutes)
    offline_cutoff = to_iso(now - timedelta(minutes=settings.offline_after_minutes))
    rows = _fetch(conn, _PENDING_SQL, (offline_cutoff, settings.max_events_per_run))
    sent = dry_run = suppressed = failed = 0
    for row in rows:
        event_id, device_id, kind, raw_details, _ = row
        reason = _suppression_reason(conn, row, cooldown)
        if reason is not None:
            repo.add_notification(
                event_id=event_id,
                channel=ALL_CHANNELS,
                status="suppressed",
                sent_at=now,
                error=reason,
            )
            suppressed += 1
            continue
        if settings.dry_run:
            repo.add_notification(
                event_id=event_id, channel=DRY_RUN_CHANNEL, status="dry_run", sent_at=now
            )
            dry_run += 1
            logger.info("dry-run: alert for event %s (%s) not sent", event_id, kind)
            continue
        message = _build_message(conn, event_id, device_id, kind, raw_details)
        for notifier in notifiers:
            try:
                notifier.send(message)
            except NotifierError as exc:
                repo.add_notification(
                    event_id=event_id,
                    channel=notifier.name,
                    status="failed",
                    sent_at=now,
                    error=type(exc).__name__,
                )
                failed += 1
            else:
                repo.add_notification(
                    event_id=event_id, channel=notifier.name, status="sent", sent_at=now
                )
                sent += 1
    return AlertRunSummary(len(rows), sent, dry_run, suppressed, failed, latency_events)
