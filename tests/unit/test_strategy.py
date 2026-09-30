"""Offline checks for explicit ARP selection and bounded passive fallback."""

from ipaddress import IPv4Network

import pytest

from nettracker.discovery.arp import ActiveDiscoveryError
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError
from nettracker.discovery.strategy import discover_with_fallback

ALLOWED = [IPv4Network("192.168.1.0/24")]
NEIGHBOR = [Neighbor("192.168.1.2", "00:11:22:33:44:55")]


def test_default_reads_passive_only() -> None:
    result = discover_with_fallback(
        ALLOWED,
        active_reader=lambda *_: pytest.fail("active discovery called by default"),
        passive_reader=lambda _: NEIGHBOR,
    )
    assert result.neighbors == NEIGHBOR
    assert result.source == "system_neighbor_cache"
    assert not result.degraded


def test_active_success_does_not_read_passive() -> None:
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.0/24",
        active_enabled=True,
        active_reader=lambda *_: NEIGHBOR,
        passive_reader=lambda _: pytest.fail("unexpected passive fallback"),
    )
    assert result.source == "active_arp"
    assert not result.degraded


def test_raw_arp_unavailable_uses_visible_passive_fallback(caplog: pytest.LogCaptureFixture) -> None:
    def unavailable(target: str, subnets: list[IPv4Network]) -> list[Neighbor]:
        raise ActiveDiscoveryError("simulated missing privilege")

    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.0/24",
        active_enabled=True,
        active_reader=unavailable,
        passive_reader=lambda _: NEIGHBOR,
    )
    assert result.neighbors == NEIGHBOR
    assert result.degraded
    assert "degraded mode" in caplog.text


def test_invalid_target_never_calls_a_reader() -> None:
    with pytest.raises(ScopeError):
        discover_with_fallback(
            ALLOWED,
            target="8.8.8.8",
            active_enabled=True,
            active_reader=lambda *_: pytest.fail("active called"),
            passive_reader=lambda _: pytest.fail("passive called"),
        )
