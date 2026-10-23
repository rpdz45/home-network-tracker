"""Read-only SQL for the dashboard. Nothing here writes to the database."""

import sqlite3
from pathlib import Path
from typing import Any

from nettracker.db import LATEST_VERSION, connect
from nettracker.errors import DatabaseError

DEVICE_LIMIT = 500
EVENT_LIMIT = 100
DETAIL_LIMIT = 25

_VERSION_SQL = "SELECT MAX(version) FROM schema_version"
_DEVICES_SQL = (
    "SELECT d.id, d.mac, d.alias, d.hostname, d.vendor, d.status, d.is_randomized_mac, "
    "d.first_seen, d.last_seen, "
    "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id AND s.source = 'discovery' "
    "ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) AS ip, "
    "(SELECT m.online FROM monitor_state m WHERE m.device_id = d.id) AS ping_online "
    "FROM devices d WHERE d.merged_into IS NULL ORDER BY d.last_seen DESC, d.id DESC LIMIT ?"
)
_DEVICE_SQL = "SELECT * FROM devices WHERE id = ?"
_SIGHTINGS_SQL = (
    "SELECT source, ip, online, latency_ms, packet_loss_pct, seen_at FROM sightings "
    "WHERE device_id = ? ORDER BY seen_at DESC, id DESC LIMIT ?"
)
_DEVICE_EVENTS_SQL = (
    "SELECT e.id, e.kind, e.details, e.created_at, "
    "(SELECT GROUP_CONCAT(n.status) FROM notifications n WHERE n.event_id = e.id) AS statuses "
    "FROM events e WHERE e.device_id = ? ORDER BY e.id DESC LIMIT ?"
)
_EVENTS_SQL = (
    "SELECT e.id, e.device_id, e.kind, e.details, e.created_at, d.alias, d.hostname, d.mac, "
    "(SELECT GROUP_CONCAT(n.status) FROM notifications n WHERE n.event_id = e.id) AS statuses "
    "FROM events e LEFT JOIN devices d ON d.id = e.device_id ORDER BY e.id DESC LIMIT ?"
)


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open the database for reading only; refuse a missing or outdated schema."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA query_only = ON")
        version = conn.execute(_VERSION_SQL).fetchone()[0]
    except sqlite3.Error as exc:
        conn.close()
        raise DatabaseError(f"cannot read database: {exc}") from exc
    if version is None or version < LATEST_VERSION:
        conn.close()
        raise DatabaseError("database schema is missing or outdated: run 'nettracker init-db'")
    return conn


def _all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot read database: {exc}") from exc


def list_devices(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Unmerged devices, most recently seen first."""
    return _all(conn, _DEVICES_SQL, (DEVICE_LIMIT,))


def get_device(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row | None:
    rows = _all(conn, _DEVICE_SQL, (device_id,))
    return rows[0] if rows else None


def device_sightings(conn: sqlite3.Connection, device_id: int) -> list[sqlite3.Row]:
    return _all(conn, _SIGHTINGS_SQL, (device_id, DETAIL_LIMIT))


def device_events(conn: sqlite3.Connection, device_id: int) -> list[sqlite3.Row]:
    return _all(conn, _DEVICE_EVENTS_SQL, (device_id, DETAIL_LIMIT))


def recent_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return _all(conn, _EVENTS_SQL, (EVENT_LIMIT,))
