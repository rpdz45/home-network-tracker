"""Explicit router DNS enrichment of one recorded device; no inventory mutation."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv4Network

from nettracker.db.network_identity import IdentityObservation, save_observations
from nettracker.discovery.router_dns import PTRLookup, collect_router_dns
from nettracker.errors import DatabaseError

_BINDING_SQL = (
    "SELECT d.mac, d.status, d.merged_into, "
    "(SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
    "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) "
    "FROM devices d WHERE d.id = ?"
)
_AMBIGUITY_SQL = (
    "SELECT COUNT(*) FROM devices d WHERE d.merged_into IS NULL "
    "AND (SELECT s.ip FROM sightings s WHERE s.device_id = d.id "
    "AND s.source = 'discovery' ORDER BY s.seen_at DESC, s.id DESC LIMIT 1) = ?"
)


def enrich_router_dns(
    conn: sqlite3.Connection,
    *,
    device_id: int,
    server: str,
    allowed_subnets: tuple[IPv4Network, ...],
    enabled: bool = False,
    timeout: float = 1.5,
    lookup: PTRLookup | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Collect and persist DNS evidence, rechecking MAC/IP after network activity.

    The caller must own authorization. No transaction may span the DNS query.
    Scope, server and timeout validation are delegated to collect_router_dns.
    """
    if enabled is not True:
        raise ValueError("router DNS enrichment requires explicit authorization")
    if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id <= 0:
        raise ValueError("invalid device ID")
    if conn.in_transaction:
        raise ValueError("DNS enrichment requires no open transaction")
    try:
        binding = conn.execute(_BINDING_SQL, (device_id,)).fetchone()
        if binding is None or binding[1] == "ignored" or binding[2] is not None:
            raise ValueError("device is missing, ignored or merged")
        mac, ip = binding[0], binding[3]
        if not isinstance(mac, str) or not isinstance(ip, str):
            raise ValueError("device has no usable recorded MAC/IP binding")
        matches = conn.execute(_AMBIGUITY_SQL, (ip,)).fetchone()
        if matches is None or matches[0] != 1:
            raise ValueError("IP is ambiguous in the recorded inventory")
    except sqlite3.Error:
        raise DatabaseError("cannot read DNS enrichment inventory") from None
    result = collect_router_dns(
        ip,
        server=server,
        allowed_subnets=allowed_subnets,
        enabled=True,
        timeout=timeout,
        lookup=lookup,
        clock=clock,
    )
    if result.status == "ok":
        observations = tuple(
            IdentityObservation("hostname", "dns_ptr", result.server, name, result.retrieved_at)
            for name in result.names
        )
    else:
        observations = (
            IdentityObservation(
                "hostname", "dns_ptr", result.server, None, result.retrieved_at, result.status
            ),
        )
    return save_observations(
        conn,
        device_id=device_id,
        matched_mac=mac,
        matched_ip=ip,
        observations=observations,
        confirmed=True,
        now=clock(),
    )
