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


def test_raw_arp_unavailable_uses_visible_passive_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
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


def unavailable_arp(_target: str, _subnets: list[IPv4Network]) -> list[Neighbor]:
    raise ActiveDiscoveryError("simulated ARP unavailable")


def test_nmap_is_never_run_without_its_opt_in() -> None:
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.0/24",
        active_enabled=True,
        active_reader=unavailable_arp,
        nmap_reader=lambda *_: pytest.fail("nmap was not opted in"),
        passive_reader=lambda _: NEIGHBOR,
    )
    assert result.source == "system_neighbor_cache"


def test_nmap_fallback_stays_active_and_reports_degradation() -> None:
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.0/24",
        active_enabled=True,
        nmap_enabled=True,
        active_reader=unavailable_arp,
        nmap_reader=lambda *_: NEIGHBOR,
        passive_reader=lambda _: pytest.fail("unexpected cache fallback"),
    )
    assert result.neighbors == NEIGHBOR
    assert result.source == "active_nmap"
    assert result.degraded


def test_nmap_failure_uses_cache(caplog: pytest.LogCaptureFixture) -> None:
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.0/24",
        active_enabled=True,
        nmap_enabled=True,
        active_reader=unavailable_arp,
        nmap_reader=unavailable_arp,
        passive_reader=lambda _: NEIGHBOR,
    )
    assert result.source == "system_neighbor_cache"
    assert result.degraded
    assert "nmap fallback unavailable" in caplog.text


def test_nmap_scope_error_is_not_a_reason_for_passive_fallback() -> None:
    def bad_response(_target: str, _subnets: list[IPv4Network]) -> list[Neighbor]:
        raise ScopeError("outside target")

    with pytest.raises(ScopeError):
        discover_with_fallback(
            ALLOWED,
            target="192.168.1.0/24",
            active_enabled=True,
            nmap_enabled=True,
            active_reader=unavailable_arp,
            nmap_reader=bad_response,
            passive_reader=lambda _: pytest.fail("scope error hidden"),
        )


def test_passive_mode_ignores_nmap_opt_in() -> None:
    result = discover_with_fallback(
        ALLOWED,
        nmap_enabled=True,
        active_reader=lambda *_: pytest.fail("unexpected ARP"),
        nmap_reader=lambda *_: pytest.fail("unexpected nmap"),
        passive_reader=lambda _: [],
    )
    assert result.source == "system_neighbor_cache"


def test_successful_arp_never_tries_nmap() -> None:
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.2",
        active_enabled=True,
        nmap_enabled=True,
        active_reader=lambda *_: NEIGHBOR,
        nmap_reader=lambda *_: pytest.fail("unexpected nmap"),
    )
    assert result.source == "active_arp"


def test_oversized_target_never_reaches_any_reader() -> None:
    with pytest.raises(ScopeError, match="256-address"):
        discover_with_fallback(
            [IPv4Network("192.168.0.0/16")],
            target="192.168.0.0/16",
            active_enabled=True,
            nmap_enabled=True,
            active_reader=lambda *_: pytest.fail("unexpected ARP"),
            nmap_reader=lambda *_: pytest.fail("unexpected nmap"),
            passive_reader=lambda _: pytest.fail("unexpected cache"),
        )


def test_missing_target_is_an_error() -> None:
    with pytest.raises(ValueError, match="explicit target"):
        discover_with_fallback(ALLOWED, active_enabled=True, nmap_enabled=True)


def test_default_nmap_backend_receives_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[IPv4Network], bool, float]] = []

    def fake_nmap(
        target: str, subnets: list[IPv4Network], *, enabled: bool, timeout: float
    ) -> list[Neighbor]:
        calls.append((target, subnets, enabled, timeout))
        return NEIGHBOR

    monkeypatch.setattr("nettracker.discovery.strategy.discover_nmap", fake_nmap)
    result = discover_with_fallback(
        ALLOWED,
        target="192.168.1.2",
        active_enabled=True,
        nmap_enabled=True,
        nmap_timeout=9,
        active_reader=unavailable_arp,
    )
    assert result.source == "active_nmap"
    assert calls == [("192.168.1.2", ALLOWED, True, 9)]
