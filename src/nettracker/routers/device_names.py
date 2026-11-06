"""Read-only matching of router-reported names to recorded discovery bindings."""

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from typing import Literal

RouterNameSource = Literal["livebox5", "bbox"]
MAX_NAMES = 512


@dataclass(frozen=True)
class RouterName:
    mac: str
    ip: str
    name: str


@dataclass(frozen=True)
class NameCandidate:
    device_id: int
    matched_mac: str
    matched_ip: str
    name: str
    source: RouterNameSource
    endpoint: str
    retrieved_at: datetime


def _mac(value: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", value) is None:
        raise ValueError("invalid router name MAC")
    octets = bytes.fromhex(value.replace(":", ""))
    if octets[0] & 1 or not any(octets):
        raise ValueError("router name MAC must be nonzero and unicast")
    return value.upper()


def preview_names(
    conn: sqlite3.Connection,
    names: tuple[RouterName, ...],
    *,
    source: RouterNameSource,
    endpoint: str,
    retrieved_at: datetime,
    secret: str,
    now: datetime | None = None,
) -> tuple[NameCandidate, ...]:
    """Propose names without writing, collecting, changing aliases or proving identity.

    The caller supplies an authorized snapshot, its actual retrieval time and the
    credential to exclude from names. A later save must recheck each binding and
    require authenticated confirmation; these proposals are not write authority.
    Duplicate MACs or IPs are excluded on either side, including ignored devices.
    """
    if source not in {"livebox5", "bbox"} or len(names) > MAX_NAMES:
        raise ValueError("unsupported router source or oversized name batch")
    endpoint = str(IPv4Address(endpoint))
    timestamp = retrieved_at
    clock = now or datetime.now(UTC)
    if timestamp.utcoffset() is None or clock.utcoffset() is None:
        raise ValueError("router name timestamps must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    if not 0 <= (clock - timestamp).total_seconds() <= 600:
        raise ValueError("router snapshot is expired or from the future")
    if not secret:
        raise ValueError("credential exclusion requires a nonempty secret")
    normalized: list[RouterName] = []
    for item in names:
        mac = _mac(item.mac)
        ip = str(IPv4Address(item.ip))
        normalized.append(RouterName(mac, ip, item.name))
    mac_counts = Counter(item.mac for item in normalized)
    ip_counts = Counter(item.ip for item in normalized)
    bindings = conn.execute(
        "SELECT d.id, d.mac, d.status, "
        "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
        "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) "
        "FROM devices d WHERE d.merged_into IS NULL"
    ).fetchall()
    inventory_ips = Counter(row[3] for row in bindings if row[3] is not None)
    inventory_macs = Counter(str(row[1]).upper() for row in bindings)
    by_mac = {str(row[1]).upper(): row for row in bindings}
    candidates: list[NameCandidate] = []
    for item in normalized:
        binding = by_mac.get(item.mac)
        name = item.name.strip()
        if (
            mac_counts[item.mac] != 1
            or ip_counts[item.ip] != 1
            or inventory_macs[item.mac] != 1
            or inventory_ips[item.ip] != 1
            or binding is None
            or binding[2] == "ignored"
            or binding[3] != item.ip
            or not 1 <= len(name) <= 128
            or not item.name.isprintable()
            or secret in item.name
        ):
            continue
        candidates.append(
            NameCandidate(binding[0], binding[1], item.ip, name, source, endpoint, timestamp)
        )
    return tuple(candidates)
