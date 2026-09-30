"""Choose active ARP only on explicit request, with a visible passive fallback."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Network

from nettracker.discovery.arp import ActiveDiscoveryError, discover_arp
from nettracker.discovery.passive import Neighbor, read_neighbors
from nettracker.discovery.scope import require_allowed_target

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
) -> DiscoveryResult:
    """Fallback only when a scoped, explicitly enabled ARP attempt is unavailable."""
    if not allowed_subnets:
        raise ValueError("allowed_subnets must not be empty")
    if not active_enabled:
        logger.info("passive mode: system neighbor cache only")
        return DiscoveryResult(passive_reader(allowed_subnets), "system_neighbor_cache", False)
    if target is None:
        raise ValueError("active discovery requires an explicit target")
    require_allowed_target(target, allowed_subnets)
    try:
        if active_reader is None:
            neighbors = discover_arp(target, allowed_subnets, enabled=True)
        else:
            neighbors = active_reader(target, allowed_subnets)
    except ActiveDiscoveryError as exc:
        logger.warning("degraded mode: system neighbor cache only (%s)", exc)
        return DiscoveryResult(passive_reader(allowed_subnets), "system_neighbor_cache", True)
    return DiscoveryResult(neighbors, "active_arp", False)
