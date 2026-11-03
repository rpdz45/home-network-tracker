"""Versioned identity evidence storage, independent of trust and presence."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from typing import Literal

from nettracker.errors import DatabaseError

IdentityField = Literal["hostname", "interface_vendor", "brand", "model", "device_type"]
IdentitySource = Literal["dns_ptr", "mdns", "ssdp", "ipp", "snmp", "cim", "oui"]
IdentityStatus = Literal[
    "reported", "no_record", "timeout", "unavailable", "invalid_response",
    "access_denied", "not_supported",
]
FIELDS = {"hostname", "interface_vendor", "brand", "model", "device_type"}
SOURCES = {"dns_ptr", "mdns", "ssdp", "ipp", "snmp", "cim", "oui"}
STATUSES = {
    "reported", "no_record", "timeout", "unavailable", "invalid_response",
    "access_denied", "not_supported",
}

# Immutable V4 schema: future schema changes require a new migration.
NETWORK_IDENTITY_V4: tuple[str, ...] = (
    """
    CREATE TABLE network_identity_observations (
        id INTEGER PRIMARY KEY,
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        matched_mac TEXT NOT NULL,
        matched_ip TEXT NOT NULL,
        field TEXT NOT NULL CHECK (field IN (
            'hostname', 'interface_vendor', 'brand', 'model', 'device_type')),
        source TEXT NOT NULL CHECK (source IN (
            'dns_ptr', 'mdns', 'ssdp', 'ipp', 'snmp', 'cim', 'oui')),
        endpoint TEXT NOT NULL,
        value TEXT CHECK (value IS NULL OR length(value) BETWEEN 1 AND 253),
        status TEXT NOT NULL CHECK (status IN (
            'reported', 'no_record', 'timeout', 'unavailable', 'invalid_response',
            'access_denied', 'not_supported')),
        retrieved_at TEXT NOT NULL,
        stored_at TEXT NOT NULL,
        CHECK ((status = 'reported' AND value IS NOT NULL)
            OR (status <> 'reported' AND value IS NULL))
    )
    """,
    "CREATE INDEX idx_network_identity_device ON network_identity_observations "
    "(device_id, retrieved_at DESC, id DESC)",
    "CREATE UNIQUE INDEX idx_network_identity_repeat ON network_identity_observations "
    "(device_id, matched_mac, matched_ip, field, source, endpoint, "
    "IFNULL(value, ''), status, retrieved_at)",
)


@dataclass(frozen=True)
class IdentityObservation:
    field: IdentityField
    source: IdentitySource
    endpoint: str
    value: str | None
    retrieved_at: datetime
    status: IdentityStatus = "reported"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("identity timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _validate(observation: IdentityObservation, now: datetime) -> str:
    if observation.field not in FIELDS or observation.source not in SOURCES:
        raise ValueError("unsupported identity field or source")
    if observation.status not in STATUSES:
        raise ValueError("unsupported identity status")
    if observation.source == "dns_ptr" and observation.field != "hostname":
        raise ValueError("DNS PTR is not a brand or model source")
    if observation.source == "oui" and observation.field != "interface_vendor":
        raise ValueError("OUI is not a product brand or model source")
    IPv4Address(observation.endpoint)
    retrieved = _utc(observation.retrieved_at)
    if not 0 <= (now - retrieved).total_seconds() <= 600:
        raise ValueError("identity observation is expired or from the future")
    value = observation.value
    if observation.status == "reported":
        if not isinstance(value, str) or not 1 <= len(value) <= 253 or not value.strip():
            raise ValueError("reported identity requires a bounded nonempty value")
        if not value.isprintable():
            raise ValueError("control characters are forbidden in identity values")
    elif value is not None:
        raise ValueError("failed lookups must not contain an identity value")
    return retrieved.isoformat()


def save_observations(
    conn: sqlite3.Connection,
    *,
    device_id: int,
    matched_mac: str,
    matched_ip: str,
    observations: tuple[IdentityObservation, ...],
    confirmed: bool = False,
    now: datetime | None = None,
) -> int:
    """Save a bounded batch against the latest observed MAC/IP, never changing devices.

    The caller owns authenticated consent and authorized network collection. This
    function emits no packets, creates no schema and never commits a caller's transaction.
    """
    if confirmed is not True:
        raise ValueError("saving identity evidence requires explicit confirmation")
    if (
        not isinstance(device_id, int)
        or isinstance(device_id, bool)
        or device_id <= 0
        or not 1 <= len(observations) <= 64
    ):
        raise ValueError("invalid device or identity batch size")
    IPv4Address(matched_ip)
    stored = _utc(now or datetime.now(UTC))
    retrieved = tuple(_validate(observation, stored) for observation in observations)
    try:
        conn.execute("SAVEPOINT network_identity_write")
        try:
            binding = conn.execute(
                "SELECT d.mac, d.merged_into, d.status, "
                "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
                "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) "
                "FROM devices d WHERE d.id = ?", (device_id,),
            ).fetchone()
            if (
                binding is None
                or binding[0] != matched_mac
                or binding[1] is not None
                or binding[3] != matched_ip
            ):
                raise ValueError("device MAC/IP binding changed or is unavailable")
            if binding[2] == "ignored":
                raise ValueError("ignored devices must not be enriched")
            matches = conn.execute(
                "SELECT COUNT(*) FROM devices d WHERE d.merged_into IS NULL "
                "AND (SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
                "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) = ?",
                (matched_ip,),
            ).fetchone()
            if matches is None or matches[0] != 1:
                raise ValueError("IP is ambiguous in the recorded inventory")
            written = 0
            for observation, timestamp in zip(observations, retrieved, strict=True):
                cursor = conn.execute(
                    "INSERT INTO network_identity_observations "
                    "(device_id, matched_mac, matched_ip, field, source, endpoint, value, "
                    "status, retrieved_at, stored_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT DO NOTHING",
                    (device_id, matched_mac, matched_ip, observation.field, observation.source,
                     observation.endpoint, observation.value, observation.status,
                     timestamp, stored.isoformat()),
                )
                written += cursor.rowcount
            conn.execute("RELEASE SAVEPOINT network_identity_write")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK TO SAVEPOINT network_identity_write")
                conn.execute("RELEASE SAVEPOINT network_identity_write")
            raise
    except sqlite3.Error:
        raise DatabaseError("network identity storage failed") from None
    return written


def current_observations(
    conn: sqlite3.Connection, device_id: int, *, limit: int = 100
) -> list[sqlite3.Row]:
    """Read recorded evidence for the current observed binding; never contact devices."""
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("identity result limit must be between 1 and 500")
    try:
        rows = conn.execute(
            "SELECT o.* FROM network_identity_observations o "
            "JOIN devices d ON d.id = o.device_id AND d.mac = o.matched_mac "
            "WHERE o.device_id = ? AND d.merged_into IS NULL "
            "AND o.matched_ip = (SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
            "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) "
            "ORDER BY o.retrieved_at DESC, o.id DESC LIMIT ?", (device_id, limit),
        ).fetchall()
    except sqlite3.Error:
        raise DatabaseError("network identity lookup failed") from None
    if any(not isinstance(row, sqlite3.Row) for row in rows):
        raise DatabaseError("identity lookup requires the repository row factory")
    return list(rows)
