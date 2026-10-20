"""Opt-in raw ARP discovery. This module alone needs raw-packet privileges."""

from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network

from nettracker.db.repository import normalize_mac
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import NetTrackerError

MAX_ADDRESSES = 256


class ActiveDiscoveryError(NetTrackerError):
    """Raw ARP discovery is unavailable or failed."""


def _send_arp(target: str, timeout: float) -> list[Neighbor]:
    """Send ARP through Scapy only after discover_arp validates the target."""
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp

        answered, _ = srp(
            Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=target),
            timeout=timeout,
            retry=0,
            verbose=False,
        )
    except (OSError, RuntimeError, ImportError) as exc:
        raise ActiveDiscoveryError(
            "raw ARP unavailable: check Npcap on Windows or raw-socket rights on Linux"
        ) from exc
    return [Neighbor(str(packet.psrc), str(packet.hwsrc)) for _, packet in answered]


Sender = Callable[[str, float], list[Neighbor]]


def discover_arp(
    target: str,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    sender: Sender = _send_arp,
    timeout: float = 2.0,
) -> list[Neighbor]:
    """Probe an explicitly authorized RFC1918 IPv4 target, never by default."""
    if not enabled:
        raise ActiveDiscoveryError("active ARP discovery must be explicitly enabled")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    parsed = require_allowed_target(target, allowed_subnets)
    if isinstance(parsed, IPv4Network) and parsed.num_addresses > MAX_ADDRESSES:
        raise ScopeError("ARP target exceeds the 256-address safety limit")
    results: dict[tuple[str, str], Neighbor] = {}
    for neighbor in sender(str(parsed), timeout):
        response = require_allowed_target(neighbor.ip, allowed_subnets)
        if not isinstance(response, IPv4Address):
            raise ScopeError("ARP response is not a host address")
        if isinstance(parsed, IPv4Network):
            if response not in parsed:
                raise ScopeError("ARP response lies outside requested target")
        elif response != parsed:
            raise ScopeError("ARP response lies outside requested target")
        mac = normalize_mac(neighbor.mac)
        if mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1:
            continue
        ip = str(response)
        results[(ip, mac)] = Neighbor(ip, mac)
    return list(results.values())
