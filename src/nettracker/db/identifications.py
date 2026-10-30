"""Explicit, atomic local storage of reported Fing identities; no network access."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network

from nettracker.db.repository import normalize_mac, to_iso
from nettracker.discovery.fing import FingInventory
from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import DatabaseError, NetTrackerError

MAX_PREVIEW_AGE_SECONDS = 600
_LOCAL_SQL = (
    "SELECT d.id, d.mac, "
    "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id AND s.source = 'discovery' "
    "ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) AS ip "
    "FROM devices d WHERE d.merged_into IS NULL "
    "ORDER BY d.last_seen DESC, d.id DESC LIMIT 500"
)
_WRITE_SQL = """
INSERT INTO device_identifications (
    device_id, source, network_id, matched_mac, matched_ip, reported_name,
    manufacturer, model, device_type, retrieved_at, stored_at
) VALUES (?, 'fing_local_api', ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(device_id, source) DO UPDATE SET
    network_id = excluded.network_id,
    matched_mac = excluded.matched_mac,
    matched_ip = excluded.matched_ip,
    reported_name = excluded.reported_name,
    manufacturer = excluded.manufacturer,
    model = excluded.model,
    device_type = excluded.device_type,
    retrieved_at = excluded.retrieved_at,
    stored_at = excluded.stored_at
WHERE excluded.retrieved_at > device_identifications.retrieved_at
"""


class IdentificationError(NetTrackerError):
    """A sanitized refusal to save an invalid or stale identification preview."""


@dataclass(frozen=True)
class ImportSummary:
    stored: int
    unmatched: int
    unchanged: int


def _validate(
    inventory: FingInventory, networks: list[IPv4Network], now: datetime
) -> tuple[str, str]:
    try:
        retrieved, stored = to_iso(inventory.retrieved_at), to_iso(now)
        age = (now - inventory.retrieved_at).total_seconds()
        if not 0 <= age <= MAX_PREVIEW_AGE_SECONDS:
            raise ValueError("stale preview")
        if inventory.source != "fing_local_api" or not 1 <= len(inventory.network_id) <= 128:
            raise ValueError("invalid source")
        if not networks or len(inventory.devices) > 1024:
            raise ValueError("invalid scope or inventory size")
        for network in networks:
            require_allowed_target(str(network), networks)
        macs: set[str] = set()
        ips: set[str] = set()
        for device in inventory.devices:
            mac = normalize_mac(device.mac)
            octets = bytes.fromhex(mac.replace(":", ""))
            if mac != device.mac or mac in macs or not any(octets) or octets[0] & 1:
                raise ValueError("invalid or duplicate MAC")
            macs.add(mac)
            if not 1 <= len(device.addresses) <= 16:
                raise ValueError("invalid address count")
            for ip in device.addresses:
                if str(IPv4Address(ip)) != ip or ip in ips:
                    raise ValueError("ambiguous address")
                require_allowed_target(ip, networks)
                ips.add(ip)
            for value in (device.name, device.manufacturer, device.model, device.device_type):
                if value is not None and (not isinstance(value, str) or len(value) > 128):
                    raise ValueError("invalid identification text")
    except (ValueError, ScopeError):
        raise IdentificationError("invalid or expired identification preview") from None
    return retrieved, stored


def save_fing_inventory(
    conn: sqlite3.Connection,
    inventory: FingInventory,
    allowed_subnets: list[IPv4Network],
    *,
    confirmed: bool = False,
    now: datetime | None = None,
) -> ImportSummary:
    """Save only exact current local matches; keep aliases, trust and presence unchanged.

    The future caller must retain the server-side preview, authenticate and check CSRF.
    A retrieval timestamp is not a scan timestamp or independent identity verification.
    """
    if confirmed is not True:
        raise IdentificationError("saving identifications requires explicit confirmation")
    retrieved, stored = _validate(inventory, allowed_subnets, now or datetime.now(UTC))
    saved = unmatched = unchanged = 0
    try:
        conn.execute("SAVEPOINT fing_identification_import")
        try:
            local = conn.execute(_LOCAL_SQL).fetchall()
            for device in inventory.devices:
                candidates = [
                    row
                    for row in local
                    if row["mac"] == device.mac and row["ip"] in device.addresses
                ]
                if len(candidates) != 1:
                    unmatched += 1
                    continue
                target = candidates[0]
                cursor = conn.execute(
                    _WRITE_SQL,
                    (
                        target["id"],
                        inventory.network_id,
                        device.mac,
                        target["ip"],
                        device.name,
                        device.manufacturer,
                        device.model,
                        device.device_type,
                        retrieved,
                        stored,
                    ),
                )
                if cursor.rowcount:
                    saved += 1
                else:
                    unchanged += 1
            conn.execute("RELEASE SAVEPOINT fing_identification_import")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK TO SAVEPOINT fing_identification_import")
                conn.execute("RELEASE SAVEPOINT fing_identification_import")
            raise
    except sqlite3.Error:
        raise DatabaseError("identification storage failed") from None
    return ImportSummary(saved, unmatched, unchanged)


def get_fing_identification(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row | None:
    """Read historical evidence for an unmerged device, not a current presence claim."""
    try:
        row = conn.execute(
            "SELECT i.* FROM device_identifications i JOIN devices d ON d.id = i.device_id "
            "WHERE i.device_id = ? AND i.source = 'fing_local_api' "
            "AND d.merged_into IS NULL AND d.mac = i.matched_mac",
            (device_id,),
        ).fetchone()
    except sqlite3.Error:
        raise DatabaseError("identification lookup failed") from None
    if row is None:
        return None
    if not isinstance(row, sqlite3.Row):
        raise DatabaseError("identification lookup requires the repository row factory")
    return row
