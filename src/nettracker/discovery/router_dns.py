"""Explicit, bounded PTR collection with provenance; no implicit system DNS."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network, ip_address
from itertools import islice
from math import isfinite
from typing import Literal

DNSStatus = Literal["ok", "no_record", "timeout", "unavailable", "invalid_response"]
_PRIVATE_RANGES = tuple(
    IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
MAX_NAMES = 8


@dataclass(frozen=True)
class DNSObservation:
    """A DNS declaration, not proof of the device's brand, model or identity."""

    ip: str
    server: str
    status: DNSStatus
    names: tuple[str, ...]
    retrieved_at: datetime
    source: Literal["dns_ptr"] = "dns_ptr"


class DNSLookupFailure(Exception):
    """Transport failure with a bounded public status and no raw response text."""

    def __init__(self, status: DNSStatus) -> None:
        if status not in ("no_record", "timeout", "unavailable"):
            raise ValueError("invalid DNS failure status")
        self.status = status
        super().__init__(status)


PTRLookup = Callable[[str, str, float], tuple[str, ...]]


def _host(value: str, networks: tuple[IPv4Network, ...]) -> str:
    address = ip_address(value)
    if not isinstance(address, IPv4Address):
        raise ValueError("only literal IPv4 hosts are supported")
    if not any(address in network for network in networks):
        raise ValueError("host is outside the authorized private scope")
    if any(
        network.prefixlen < 31
        and address in (network.network_address, network.broadcast_address)
        for network in networks
    ):
        raise ValueError("network and broadcast addresses are not hosts")
    return str(address)


def _query_ptr(ip: str, server: str, timeout: float) -> tuple[str, ...]:
    import dns.exception
    import dns.resolver
    import dns.reversename

    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [server]
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = resolver.resolve(
            dns.reversename.from_address(ip), "PTR", lifetime=timeout, search=False
        )
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer) as exc:
        raise DNSLookupFailure("no_record") from exc
    except dns.exception.Timeout as exc:
        raise DNSLookupFailure("timeout") from exc
    except (dns.exception.DNSException, OSError) as exc:
        raise DNSLookupFailure("unavailable") from exc
    return tuple(record.to_text() for record in islice(answer, MAX_NAMES))


def _name(raw: str) -> str | None:
    if len(raw) > 254:
        return None
    value = raw.removesuffix(".").casefold()
    if not value or len(value) > 253:
        return None
    for label in value.split("."):
        if not 1 <= len(label) <= 63 or label.startswith("-") or label.endswith("-"):
            return None
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
            for character in label
        ):
            return None
    return value


def collect_router_dns(
    ip: str,
    *,
    server: str,
    allowed_subnets: tuple[IPv4Network, ...],
    enabled: bool = False,
    timeout: float = 1.5,
    lookup: PTRLookup | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DNSObservation:
    """Collect PTR names only after explicit consent and validation of both hosts.

    No fallback to a public or system resolver is performed. Results do not update
    inventory by themselves; persistence and UI integration are separate layers.
    """
    if enabled is not True:
        raise ValueError("router DNS collection requires explicit authorization")
    if not allowed_subnets or any(
        not isinstance(network, IPv4Network)
        or not any(network.subnet_of(private) for private in _PRIVATE_RANGES)
        for network in allowed_subnets
    ):
        raise ValueError("an explicit RFC1918 IPv4 scope is required")
    if isinstance(timeout, bool) or not isfinite(timeout) or not 0.2 <= timeout <= 5.0:
        raise ValueError("timeout must be between 0.2 and 5 seconds")
    target = _host(ip, allowed_subnets)
    dns_server = _host(server, allowed_subnets)
    status: DNSStatus
    names: tuple[str, ...] = ()
    try:
        response = (lookup or _query_ptr)(target, dns_server, timeout)
        parsed = tuple(_name(raw) for raw in islice(response, MAX_NAMES))
        if any(name is None for name in parsed):
            status = "invalid_response"
        else:
            names = tuple(dict.fromkeys(name for name in parsed if name is not None))
            status = "ok" if names else "no_record"
    except DNSLookupFailure as exc:
        status = exc.status
    retrieved_at = clock()
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return DNSObservation(target, dns_server, status, names, retrieved_at.astimezone(UTC))
