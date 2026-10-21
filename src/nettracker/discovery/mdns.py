"""Opt-in direct-unicast mDNS PTR queries to explicitly scoped IPv4 devices."""

import logging
import math
import re
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.rdtypes.ANY.PTR
import dns.reversename

from nettracker.discovery.scope import ScopeError, require_allowed_target

logger = logging.getLogger(__name__)
Lookup = Callable[[str, float], str | None]
_LABEL = re.compile(rb"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)


def _local_hostname(name: dns.name.Name) -> str | None:
    labels = name.labels
    if len(labels) < 3 or labels[-1] != b"" or labels[-2].lower() != b"local":
        return None
    if any(_LABEL.fullmatch(label) is None for label in labels[:-1]):
        return None
    hostname = b".".join(labels[:-1])
    return hostname.decode("ascii").lower() if len(hostname) <= 253 else None


def _query_hostname(ip: str, timeout: float) -> str | None:
    """Use RFC 6762 sections 5.5/6.7, not multicast or the system DNS resolver."""
    owner = dns.reversename.from_address(ip)
    query = dns.message.make_query(owner, dns.rdatatype.PTR, flags=0, use_edns=False)
    response = dns.query.udp(
        query,
        ip,
        port=5353,
        timeout=timeout,
        ignore_unexpected=True,
        ignore_errors=True,
    )
    if (
        not query.is_response(response)
        or response.rcode() != dns.rcode.NOERROR
        or response.flags & dns.flags.TC
    ):
        return None
    names: set[str] = set()
    for records in response.answer:
        if (
            records.name != owner
            or records.rdtype != dns.rdatatype.PTR
            or records.rdclass != dns.rdataclass.IN
            or records.ttl <= 0
        ):
            continue
        for record in records:
            if isinstance(record, dns.rdtypes.ANY.PTR.PTR):
                hostname = _local_hostname(record.target)
                if hostname is not None:
                    names.add(hostname)
    return next(iter(names)) if len(names) == 1 else None


def mdns_hostname(
    ip: str,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    timeout: float = 1.0,
    lookup: Lookup | None = None,
) -> str | None:
    """Enrich one observed host; no service browsing, retries or DNS fallback.

    The transport is replaceable. Timeout/permission/protocol failures leave the
    hostname unknown. Scope errors are never swallowed. Names are untrusted hints.
    """
    if not enabled:
        return None
    target = require_allowed_target(ip, allowed_subnets)
    if not isinstance(target, IPv4Address):
        raise ScopeError("mDNS requires an IPv4 host, not a CIDR")
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 5.0:
        raise ValueError("mDNS timeout must be finite and between 0.1 and 5 seconds")
    try:
        return (lookup or _query_hostname)(str(target), timeout)
    except (OSError, dns.exception.DNSException) as exc:
        logger.debug("mDNS lookup unavailable: %s", type(exc).__name__)
        return None
