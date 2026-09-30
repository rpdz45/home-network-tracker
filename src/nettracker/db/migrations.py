"""Versioned schema migrations.

Each migration is a tuple of SQL statements applied in a single transaction. The applied
versions are recorded in ``schema_version``. Never edit a released migration: add a new one.
"""

import sqlite3

from nettracker.errors import DatabaseError

_V1: tuple[str, ...] = (
    """
    CREATE TABLE devices (
        id                INTEGER PRIMARY KEY,
        mac               TEXT    NOT NULL UNIQUE,
        alias             TEXT,
        device_type       TEXT,
        hostname          TEXT,
        vendor            TEXT,
        is_randomized_mac INTEGER NOT NULL DEFAULT 0,
        status            TEXT    NOT NULL DEFAULT 'unknown'
                          CHECK (status IN ('known', 'unknown', 'to_confirm', 'ignored')),
        merged_into       INTEGER REFERENCES devices(id),
        first_seen        TEXT    NOT NULL,
        last_seen         TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE scans (
        id            INTEGER PRIMARY KEY,
        started_at    TEXT    NOT NULL,
        finished_at   TEXT,
        mode          TEXT    NOT NULL CHECK (mode IN ('passive', 'active')),
        subnet        TEXT,
        status        TEXT    NOT NULL CHECK (status IN ('ok', 'error', 'denied')),
        error         TEXT,
        devices_found INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE sightings (
        id              INTEGER PRIMARY KEY,
        device_id       INTEGER NOT NULL REFERENCES devices(id),
        scan_id         INTEGER REFERENCES scans(id),
        ip              TEXT    NOT NULL,
        ipv6            TEXT,
        online          INTEGER NOT NULL,
        latency_ms      REAL,
        packet_loss_pct REAL,
        seen_at         TEXT    NOT NULL
    )
    """,
    "CREATE INDEX idx_sightings_device_time ON sightings (device_id, seen_at)",
    """
    CREATE TABLE events (
        id         INTEGER PRIMARY KEY,
        device_id  INTEGER REFERENCES devices(id),
        kind       TEXT NOT NULL CHECK (kind IN (
                       'new_device', 'online', 'offline', 'latency_high',
                       'to_confirm', 'merge_suggested', 'collector_stale')),
        details    TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE notifications (
        id       INTEGER PRIMARY KEY,
        event_id INTEGER NOT NULL REFERENCES events(id),
        channel  TEXT NOT NULL,
        status   TEXT NOT NULL CHECK (status IN ('sent', 'dry_run', 'failed', 'suppressed')),
        error    TEXT,
        sent_at  TEXT NOT NULL
    )
    """,
)

MIGRATIONS: tuple[tuple[str, ...], ...] = (_V1,)
LATEST_VERSION = len(MIGRATIONS)


def _recorded_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def current_version(conn: sqlite3.Connection) -> int:
    """Return the schema version recorded in the database (0 for a new database)."""
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        return _recorded_version(conn)
    except sqlite3.Error as exc:
        raise DatabaseError(f"cannot read schema version: {exc}") from exc


def _apply(conn: sqlite3.Connection, target: int, statements: tuple[str, ...]) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _recorded_version(conn) >= target:
            conn.execute("ROLLBACK")
            return
        for statement in statements:
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (target,))
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise DatabaseError(f"migration to version {target} failed: {exc}") from exc


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database up to the latest schema version and return that version."""
    version = current_version(conn)
    if version > LATEST_VERSION:
        raise DatabaseError(
            f"database schema version {version} is newer than the supported version "
            f"{LATEST_VERSION}: upgrade nettracker"
        )
    for target in range(version + 1, LATEST_VERSION + 1):
        _apply(conn, target, MIGRATIONS[target - 1])
    return LATEST_VERSION
