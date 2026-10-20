"""Choose explicit ARP, optional nmap, then a visible passive fallback."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Network

from nettracker.discovery.arp import MAX_ADDRESSES, ActiveDiscoveryError, discover_arp
from nettracker.discovery.nmap import discover_nmap
from nettracker.discovery.passive import Neighbor, read_neighbors
from nettracker.discovery.scope import ScopeError, require_allowed_target

logger = logging.getLogger(__name__)

ActiveReader = Callable[[str, list[IPv4Network]], list[Neighbor]]
PassiveReader = Callable[[list[IPv4Network]], list[Neighbor]]


@dataclass(frozen=True)
class DiscoveryResult:
    neighbors: list[Neighbor]
    source: str
    degraded: bool


def discover_with_fallback(
    allowed_subnets: list[IPv4Network],
    *,
    target: str | None = None,
    active_enabled: bool = False,
    active_reader: ActiveReader | None = None,
    passive_reader: PassiveReader = read_neighbors,
    nmap_enabled: bool = False,
    nmap_reader: ActiveReader | None = None,
    nmap_timeout: float = 30.0,
) -> DiscoveryResult:
    """Fallback only when a scoped, explicitly enabled ARP attempt is unavailable."""
    if not allowed_subnets:
        raise ValueError("allowed_subnets must not be empty")
    if not active_enabled:
        logger.info("passive mode: system neighbor cache only")
        return DiscoveryResult(passive_reader(allowed_subnets), "system_neighbor_cache", False)
    if target is None:
        raise ValueError("active discovery requires an explicit target")
    parsed = require_allowed_target(target, allowed_subnets)
    if isinstance(parsed, IPv4Network) and parsed.num_addresses > MAX_ADDRESSES:
        raise ScopeError("active target exceeds the 256-address safety limit")
    try:
        if active_reader is None:
            neighbors = discover_arp(target, allowed_subnets, enabled=True)
        else:
            neighbors = active_reader(target, allowed_subnets)
    except ActiveDiscoveryError as exc:
        if nmap_enabled:
            logger.warning("raw ARP unavailable; trying explicitly enabled nmap fallback")
            try:
                if nmap_reader is None:
                    neighbors = discover_nmap(
                        target, allowed_subnets, enabled=True, timeout=nmap_timeout
                    )
                else:
                    neighbors = nmap_reader(target, allowed_subnets)
            except ActiveDiscoveryError as nmap_exc:
                logger.warning("nmap fallback unavailable (%s)", nmap_exc)
            else:
                return DiscoveryResult(neighbors, "active_nmap", True)
        logger.warning("degraded mode: system neighbor cache only (%s)", exc)
        return DiscoveryResult(passive_reader(allowed_subnets), "system_neighbor_cache", True)
    return DiscoveryResult(neighbors, "active_arp", False)
