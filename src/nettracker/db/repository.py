"""Data access layer. All SQL lives here."""

import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any, Literal, get_args

from nettracker.errors import DatabaseError

DeviceStatus = Literal["known", "unknown", "to_confirm", "ignored"]
EventKind = Literal[
    "new_device",
    "online",
    "offline",
    "latency_high",
    "to_confirm",
    "merge_suggested",
    "collector_stale",
]
ScanMode = Literal["passive", "active"]
ScanStatus = Literal["ok", "error", "denied"]
NotificationStatus = Literal["sent", "dry_run", "failed", "suppressed"]

_DEVICE_STATUSES: frozenset[str] = frozenset(get_args(DeviceStatus))
_EVENT_KINDS: frozenset[str] = frozenset(get_args(EventKind))
_SCAN_MODES: frozenset[str] = frozenset(get_args(ScanMode))
_SCAN_STATUSES: frozenset[str] = frozenset(get_args(ScanStatus))
_NOTIFICATION_STATUSES: frozenset[str] = frozenset(get_args(NotificationStatus))
_MAC_PATTERN = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(value: str) -> str:
    """Return the MAC address in lowercase, colon-separated form."""
    candidate = value.strip().lower().replace("-", ":")
    if not _MAC_PATTERN.match(candidate):
        raise ValueError(f"invalid MAC address: {value!r}")
    return candidate


def is_locally_administered(mac: str) -> bool:
    """Tell whether a MAC is private/random (locally administered bit set)."""
    return bool(int(normalize_mac(mac)[:2], 16) & 0x02)


def to_iso(moment: datetime) -> str:
    """Convert a timezone-aware datetime to a fixed-width ISO 8601 UTC string."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _require(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {label}: {value!r}")


@dataclass(frozen=True)
class Device:
    id: int
    mac: str
    alias: str | None
    device_type: str | None
    hostname: str | None
    vendor: str | None
    is_randomized_mac: bool
    status: DeviceStatus
    merged_into: int | None
    first_seen: str
    last_seen: str


@dataclass(frozen=True)
class Event:
    id: int
    device_id: int | None
    kind: EventKind
    details: dict[str, Any] | None
    created_at: str


def _device_from_row(row: sqlite3.Row | None) -> Device:
    if row is None:
        raise DatabaseError("device row not found")
    return Device(
        id=row["id"],
        mac=row["mac"],
        alias=row["alias"],
        device_type=row["device_type"],
        hostname=row["hostname"],
        vendor=row["vendor"],
        is_randomized_mac=bool(row["is_randomized_mac"]),
        status=row["status"],
        merged_into=row["merged_into"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
    )


def _event_from_row(row: sqlite3.Row) -> Event:
    raw_details = row["details"]
    details: dict[str, Any] | None = json.loads(raw_details) if raw_details else None
    return Event(
        id=row["id"],
        device_id=row["device_id"],
        kind=row["kind"],
        details=details,
        created_at=row["created_at"],
    )


class Repository:
    """Typed, idempotent access to the SQLite database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run the block in one transaction. Nested calls join the outer transaction."""
        if self._conn.in_transaction:
            yield
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._rollback()
            raise DatabaseError(str(exc)) from exc
        except BaseException:
            self._rollback()
            raise

    def _rollback(self) -> None:
        if self._conn.in_transaction:
            with suppress(sqlite3.Error):
                self._conn.execute("ROLLBACK")

    def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        try:
            return self._conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise DatabaseError(str(exc)) from exc

    def _fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        rows = self._fetch_all(sql, params)
        return rows[0] if rows else None

    def _insert(self, sql: str, params: tuple[Any, ...]) -> int:
        with self.transaction():
            cursor = self._conn.execute(sql, params)
        if cursor.lastrowid is None:
            raise DatabaseError("insert did not return a row id")
        return cursor.lastrowid

    def upsert_device(
        self,
        mac: str,
        *,
        seen_at: datetime,
        hostname: str | None = None,
        vendor: str | None = None,
    ) -> Device:
        """Create the device or refresh it. Safe to call repeatedly with the same data."""
        normalized = normalize_mac(mac)
        stamp = to_iso(seen_at)
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO devices (
                    mac, hostname, vendor, is_randomized_mac, first_seen, last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    hostname = COALESCE(excluded.hostname, devices.hostname),
                    vendor = COALESCE(excluded.vendor, devices.vendor),
                    first_seen = MIN(devices.first_seen, excluded.first_seen),
                    last_seen = MAX(devices.last_seen, excluded.last_seen)
                """,
                (
                    normalized,
                    hostname or None,
                    vendor or None,
                    int(is_locally_administered(normalized)),
                    stamp,
                    stamp,
                ),
            )
        row = self._fetch_one("SELECT * FROM devices WHERE mac = ?", (normalized,))
        return _device_from_row(row)

    def get_device(self, device_id: int) -> Device | None:
        row = self._fetch_one("SELECT * FROM devices WHERE id = ?", (device_id,))
        return _device_from_row(row) if row is not None else None

    def get_device_by_mac(self, mac: str) -> Device | None:
        row = self._fetch_one("SELECT * FROM devices WHERE mac = ?", (normalize_mac(mac),))
        return _device_from_row(row) if row is not None else None

    def list_devices(self, status: DeviceStatus | None = None) -> list[Device]:
        if status is None:
            rows = self._fetch_all("SELECT * FROM devices ORDER BY id")
        else:
            _require(status, _DEVICE_STATUSES, "device status")
            rows = self._fetch_all("SELECT * FROM devices WHERE status = ? ORDER BY id", (status,))
        return [_device_from_row(row) for row in rows]

    def set_status(self, device_id: int, status: DeviceStatus) -> None:
        _require(status, _DEVICE_STATUSES, "device status")
        with self.transaction():
            cursor = self._conn.execute(
                "UPDATE devices SET status = ? WHERE id = ?", (status, device_id)
            )
        if cursor.rowcount == 0:
            raise DatabaseError(f"device {device_id} not found")

    def start_scan(
        self,
        *,
        mode: ScanMode,
        started_at: datetime,
        subnet: str | None = None,
    ) -> int:
        _require(mode, _SCAN_MODES, "scan mode")
        return self._insert(
            "INSERT INTO scans (started_at, mode, subnet, status) VALUES (?, ?, ?, 'error')",
            (to_iso(started_at), mode, subnet),
        )

    def finish_scan(
        self,
        scan_id: int,
        *,
        status: ScanStatus,
        finished_at: datetime,
        devices_found: int = 0,
        error: str | None = None,
    ) -> None:
        _require(status, _SCAN_STATUSES, "scan status")
        with self.transaction():
            cursor = self._conn.execute(
                """
                UPDATE scans
                SET status = ?, finished_at = ?, devices_found = ?, error = ?
                WHERE id = ?
                """,
                (status, to_iso(finished_at), devices_found, error, scan_id),
            )
        if cursor.rowcount == 0:
            raise DatabaseError(f"scan {scan_id} not found")

    def add_sighting(
        self,
        *,
        device_id: int,
        ip: str,
        online: bool,
        seen_at: datetime,
        scan_id: int | None = None,
        ipv6: str | None = None,
        latency_ms: float | None = None,
        packet_loss_pct: float | None = None,
    ) -> int:
        ip_address(ip)
        if ipv6 is not None:
            ip_address(ipv6)
        if latency_ms is not None and latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if packet_loss_pct is not None and not 0 <= packet_loss_pct <= 100:
            raise ValueError("packet_loss_pct must be between 0 and 100")
        return self._insert(
            """
            INSERT INTO sightings (
                device_id, scan_id, ip, ipv6, online, latency_ms, packet_loss_pct, seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                scan_id,
                ip,
                ipv6,
                int(online),
                latency_ms,
                packet_loss_pct,
                to_iso(seen_at),
            ),
        )

    def add_event(
        self,
        kind: EventKind,
        *,
        created_at: datetime,
        device_id: int | None = None,
        details: Mapping[str, object] | None = None,
    ) -> int:
        _require(kind, _EVENT_KINDS, "event kind")
        payload = json.dumps(dict(details), sort_keys=True) if details else None
        return self._insert(
            "INSERT INTO events (device_id, kind, details, created_at) VALUES (?, ?, ?, ?)",
            (device_id, kind, payload, to_iso(created_at)),
        )

    def list_events(self, *, kind: EventKind | None = None, limit: int = 100) -> list[Event]:
        """Return the most recent events first."""
        if kind is None:
            rows = self._fetch_all("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        else:
            _require(kind, _EVENT_KINDS, "event kind")
            rows = self._fetch_all(
                "SELECT * FROM events WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit)
            )
        return [_event_from_row(row) for row in rows]

    def add_notification(
        self,
        *,
        event_id: int,
        channel: str,
        status: NotificationStatus,
        sent_at: datetime,
        error: str | None = None,
    ) -> int:
        _require(status, _NOTIFICATION_STATUSES, "notification status")
        return self._insert(
            "INSERT INTO notifications (event_id, channel, status, error, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, channel, status, error, to_iso(sent_at)),
        )
