"""ARP backend tests never create sockets or send packets."""

from ipaddress import IPv4Network

import pytest

from nettracker.discovery.arp import ActiveDiscoveryError, discover_arp
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]


def test_off_by_default_and_out_of_scope_never_call_sender() -> None:
    calls: list[tuple[str, float]] = []

    def sender(target: str, timeout: float) -> list[Neighbor]:
        calls.append((target, timeout))
        return [Neighbor("192.168.1.2", "02:11:22:33:44:55")]

    with pytest.raises(ActiveDiscoveryError, match="explicitly enabled"):
        discover_arp("192.168.1.0/24", ALLOWED, sender=sender)
    for target in ("8.8.8.8", "192.168.2.0/24", "router.local"):
        with pytest.raises(ScopeError):
            discover_arp(target, ALLOWED, enabled=True, sender=sender)
    assert calls == []


def test_large_target_and_invalid_timeout_never_call_sender() -> None:
    calls: list[str] = []

    def sender(target: str, timeout: float) -> list[Neighbor]:
        calls.append(target)
        return []

    with pytest.raises(ScopeError, match="256-address"):
        discover_arp("192.168.0.0/16", [IPv4Network("192.168.0.0/16")], enabled=True, sender=sender)
    with pytest.raises(ValueError, match="timeout"):
        discover_arp("192.168.1.0/24", ALLOWED, enabled=True, sender=sender, timeout=0)
    assert calls == []


def test_valid_target_deduplicates_and_rejects_outside_response() -> None:
    calls: list[tuple[str, float]] = []

    def sender(target: str, timeout: float) -> list[Neighbor]:
        calls.append((target, timeout))
        return [
            Neighbor("192.168.1.2", "02-11-22-33-44-55"),
            Neighbor("192.168.1.2", "02:11:22:33:44:55"),
            Neighbor("192.168.1.255", "ff:ff:ff:ff:ff:ff"),
        ]

    assert discover_arp("192.168.1.0/24", ALLOWED, enabled=True, sender=sender) == [
        Neighbor("192.168.1.2", "02:11:22:33:44:55")
    ]
    assert calls == [("192.168.1.0/24", 2.0)]
    with pytest.raises(ScopeError, match="outside requested"):
        discover_arp(
            "192.168.1.2",
            ALLOWED,
            enabled=True,
            sender=lambda *_: [Neighbor("192.168.1.3", "02:11:22:33:44:55")],
        )
