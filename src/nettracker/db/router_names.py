"""Explicit, atomic local storage of router-reported names; no network access."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address

from nettracker.db.repository import normalize_mac, to_iso
from nettracker.errors import DatabaseError, NetTrackerError
from nettracker.routers.device_names import NameCandidate

MAX_PREVIEW_AGE_SECONDS = 600
MAX_CANDIDATES = 512
SOURCES = frozenset({"livebox5", "bbox"})
_LOCAL_SQL = (
    "SELECT d.id, d.mac, d.status, "
    "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id AND s.source = 'discovery' "
    "ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) AS ip "
    "FROM devices d WHERE d.merged_into IS NULL"
)
_WRITE_SQL = """
INSERT INTO router_name_observations (
    device_id, source, endpoint, matched_mac, matched_ip, reported_name,
    retrieved_at, stored_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(device_id, source) DO UPDATE SET
    endpoint = excluded.endpoint,
    matched_mac = excluded.matched_mac,
    matched_ip = excluded.matched_ip,
    reported_name = excluded.reported_name,
    retrieved_at = excluded.retrieved_at,
    stored_at = excluded.stored_at
WHERE excluded.retrieved_at > router_name_observations.retrieved_at
"""


class RouterNameError(NetTrackerError):
    """A sanitized refusal to save an invalid or stale router name preview."""


@dataclass(frozen=True)
class SaveSummary:
    stored: int
    unmatched: int
    unchanged: int


def _validate(candidates: tuple[NameCandidate, ...], now: datetime) -> str:
    try:
        stamp = to_iso(now)
        if not 1 <= len(candidates) <= MAX_CANDIDATES:
            raise ValueError("invalid batch size")
        seen: set[tuple[str, str, str]] = set()
        for candidate in candidates:
            to_iso(candidate.retrieved_at)
            age = (now - candidate.retrieved_at).total_seconds()
            if not 0 <= age <= MAX_PREVIEW_AGE_SECONDS:
                raise ValueError("stale preview")
            if (
                not isinstance(candidate.device_id, int)
                or isinstance(candidate.device_id, bool)
                or candidate.device_id <= 0
                or candidate.source not in SOURCES
            ):
                raise ValueError("invalid device or source")
            if str(IPv4Address(candidate.endpoint)) != candidate.endpoint:
                raise ValueError("invalid endpoint")
            if str(IPv4Address(candidate.matched_ip)) != candidate.matched_ip:
                raise ValueError("invalid matched address")
            if normalize_mac(candidate.matched_mac) != candidate.matched_mac:
                raise ValueError("invalid matched MAC")
            octets = bytes.fromhex(candidate.matched_mac.replace(":", ""))
            if not any(octets) or octets[0] & 1:
                raise ValueError("invalid matched MAC")
            name = candidate.name
            if (
                not isinstance(name, str)
                or name != name.strip()
                or not 1 <= len(name) <= 128
                or not name.isprintable()
            ):
                raise ValueError("invalid name")
            keys = (
                ("device", str(candidate.device_id), candidate.source),
                ("mac", candidate.source, candidate.matched_mac),
                ("ip", candidate.source, candidate.matched_ip),
            )
            if any(key in seen for key in keys):
                raise ValueError("ambiguous association")
            seen.update(keys)
    except ValueError:
        raise RouterNameError("invalid or expired router name preview") from None
    return stamp


def save_router_names(
    conn: sqlite3.Connection,
    candidates: tuple[NameCandidate, ...],
    *,
    confirmed: bool = False,
    now: datetime | None = None,
) -> SaveSummary:
    """Save only names whose MAC/IP binding is still unique and current.

    The caller must authenticate, check CSRF and keep the server-side preview. Aliases,
    trust status and presence are never changed. A router-reported name is evidence of
    what the box displays, not independent verification of the physical device.
    """
    if confirmed is not True:
        raise RouterNameError("saving router names requires explicit confirmation")
    clock = now or datetime.now(UTC)
    stamp = _validate(candidates, clock)
    saved = unmatched = unchanged = 0
    try:
        conn.execute("SAVEPOINT router_name_import")
        try:
            local = conn.execute(_LOCAL_SQL).fetchall()
            mac_counts: dict[str, int] = {}
            ip_counts: dict[str, int] = {}
            for row in local:
                mac_counts[row["mac"]] = mac_counts.get(row["mac"], 0) + 1
                if row["ip"] is not None:
                    ip_counts[row["ip"]] = ip_counts.get(row["ip"], 0) + 1
            by_id = {row["id"]: row for row in local}
            for candidate in candidates:
                target = by_id.get(candidate.device_id)
                if (
                    target is None
                    or target["status"] == "ignored"
                    or target["mac"] != candidate.matched_mac
                    or target["ip"] != candidate.matched_ip
                    or mac_counts.get(candidate.matched_mac) != 1
                    or ip_counts.get(candidate.matched_ip) != 1
                ):
                    unmatched += 1
                    continue
                cursor = conn.execute(
                    _WRITE_SQL,
                    (
                        candidate.device_id,
                        candidate.source,
                        candidate.endpoint,
                        candidate.matched_mac,
                        candidate.matched_ip,
                        candidate.name,
                        to_iso(candidate.retrieved_at),
                        stamp,
                    ),
                )
                if cursor.rowcount:
                    saved += 1
                else:
                    unchanged += 1
            conn.execute("RELEASE SAVEPOINT router_name_import")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK TO SAVEPOINT router_name_import")
                conn.execute("RELEASE SAVEPOINT router_name_import")
            raise
    except sqlite3.Error:
        raise DatabaseError("router name storage failed") from None
    return SaveSummary(saved, unmatched, unchanged)


def get_router_names(conn: sqlite3.Connection, device_id: int) -> list[sqlite3.Row]:
    """Read stored evidence for an unmerged device whose MAC still matches; no refresh."""
    try:
        rows = conn.execute(
            "SELECT o.* FROM router_name_observations o JOIN devices d ON d.id = o.device_id "
            "WHERE o.device_id = ? AND d.merged_into IS NULL AND d.mac = o.matched_mac "
            "ORDER BY o.source",
            (device_id,),
        ).fetchall()
    except sqlite3.Error:
        raise DatabaseError("router name lookup failed") from None
    if any(not isinstance(row, sqlite3.Row) for row in rows):
        raise DatabaseError("router name lookup requires the repository row factory")
    return list(rows)
