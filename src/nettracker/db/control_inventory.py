"""Read-only, conservative target resolution from local discovery evidence."""

import sqlite3
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from nettracker.db.repository import to_iso
from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind

MAX_EVIDENCE = 1024


def resolve_control_target(
    conn: sqlite3.Connection,
    device_id: int,
    blocked: bool,
    *,
    router: RouterKind,
    now: datetime,
    max_age: timedelta,
) -> AccessRequest:
    """Resolve without network access, writes, or browser-supplied addresses.

    Router selection and freshness policy must come from trusted server config.
    The caller must still apply ControlGuards and adapter-level protections.
    """
    if type(device_id) is not int or device_id < 1 or type(blocked) is not bool:
        raise AccessControlError("invalid device or action")
    if not isinstance(router, RouterKind) or not timedelta(0) < max_age <= timedelta(minutes=5):
        raise ValueError("explicit router and freshness of at most five minutes required")
    upper = to_iso(now)
    lower = to_iso(now - max_age)
    try:
        rows = conn.execute(
            "SELECT d.id, d.mac, d.merged_into, s.ip, s.online, s.seen_at "
            "FROM devices d LEFT JOIN sightings s ON s.device_id = d.id "
            "AND s.source = 'discovery' AND s.seen_at >= ? "
            "WHERE d.id = ? OR s.id IS NOT NULL "
            "ORDER BY s.seen_at DESC, s.id DESC LIMIT ?",
            (lower, device_id, MAX_EVIDENCE + 1),
        ).fetchall()
    except sqlite3.Error:
        raise AccessControlError("local inventory is unavailable; no change permitted") from None
    if len(rows) > MAX_EVIDENCE:
        raise AccessControlError("inventory evidence exceeds safety limit")
    targets = [row for row in rows if row[0] == device_id]
    if not targets or any(row[2] is not None for row in targets):
        raise AccessControlError("device is missing or merged")
    if any(row[3] is None for row in targets):
        raise AccessControlError("fresh discovery evidence is required")
    addresses: set[IPv4Address] = set()
    for row in targets:
        try:
            stamp = datetime.fromisoformat(row[5])
            if to_iso(stamp) != row[5] or not lower <= row[5] <= upper:
                raise ValueError("invalid observation time")
            addresses.add(IPv4Address(row[3]))
        except (TypeError, ValueError):
            raise AccessControlError("invalid, future or non-IPv4 discovery evidence") from None
    if len(addresses) != 1:
        raise AccessControlError("recent discovery addresses are ambiguous")
    address = addresses.pop()
    if targets[0][4] != 1:
        raise AccessControlError("latest discovery does not report an online target")
    for row in rows:
        if row[0] == device_id:
            continue
        try:
            candidate = IPv4Address(row[3])
        except (TypeError, ValueError):
            continue
        if candidate == address:
            raise AccessControlError("recent address ownership is ambiguous")
    try:
        return AccessRequest(router, address, targets[0][1], blocked)
    except ValueError:
        raise AccessControlError("inventory MAC is invalid") from None
