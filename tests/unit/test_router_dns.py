"""Deterministic collector tests: no real DNS requests or user configuration."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from typing import Any

import pytest

from nettracker.discovery.router_dns import (
    DNSLookupFailure,
    DNSObservation,
    DNSStatus,
    collect_router_dns,
)

SCOPE = (IPv4Network("192.168.34.0/24"),)
NOW = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)


def collect(**changes: Any) -> DNSObservation:
    arguments: dict[str, Any] = {
        "ip": "192.168.34.230",
        "server": "192.168.34.1",
        "allowed_subnets": SCOPE,
        "enabled": True,
        "lookup": lambda *_: ("NAS-CAE.localdomain.",),
        "clock": lambda: NOW,
    }
    arguments.update(changes)
    return collect_router_dns(**arguments)


def test_normalized_names_and_provenance() -> None:
    seen: list[tuple[str, str, float]] = []

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        seen.append((ip, server, timeout))
        return ("NAS-CAE.localdomain.", "nas-cae.localdomain.", "OTHER.localdomain.")

    result = collect(lookup=lookup)
    assert seen == [("192.168.34.230", "192.168.34.1", 1.5)]
    assert result.names == ("nas-cae.localdomain", "other.localdomain")
    assert result.status == "ok"
    assert result.source == "dns_ptr"
    assert result.retrieved_at == NOW
    assert result.server == "192.168.34.1"


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"enabled": 1},
        {"enabled": "true"},
        {"ip": "8.8.8.8"},
        {"server": "8.8.8.8"},
        {"ip": "192.168.35.2"},
        {"ip": "example.org"},
        {"ip": "192.168.34.0/24"},
        {"ip": "::1"},
        {"allowed_subnets": ()},
        {"allowed_subnets": (IPv4Network("0.0.0.0/0"),)},
        {"ip": "192.168.34.255"},
        {"server": "192.168.34.0"},
        {"timeout": 0},
        {"timeout": 6},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": True},
    ],
)
def test_denied_before_transport(changes: dict[str, Any]) -> None:
    def forbidden(*_: object) -> tuple[str, ...]:
        raise AssertionError("no packets may be emitted")

    with pytest.raises(ValueError):
        collect(lookup=forbidden, **changes)


@pytest.mark.parametrize("status", ["timeout", "no_record", "unavailable"])
def test_failure_has_provenance_without_fallback(status: DNSStatus) -> None:
    calls: list[tuple[object, ...]] = []

    def failure(*args: object) -> tuple[str, ...]:
        calls.append(args)
        raise DNSLookupFailure(status)

    result = collect(lookup=failure)
    assert len(calls) == 1
    assert result.status == status
    assert result.names == ()
    assert result.retrieved_at == NOW


@pytest.mark.parametrize(
    "name",
    [
        "<script>",
        "a..local",
        "a\n.local",
        "-a.local",
        "a-.local",
        "a" * 64 + ".local",
        "a" * 255,
    ],
)
def test_invalid_answers_are_not_display_names(name: str) -> None:
    result = collect(lookup=lambda *_: (name,))
    assert result.status == "invalid_response"
    assert result.names == ()


def test_empty_response() -> None:
    assert collect(lookup=lambda *_: ()).status == "no_record"


def test_bounded_answers() -> None:
    result = collect(lookup=lambda *_: tuple(f"device-{i}.local" for i in range(50)))
    assert len(result.names) == 8


def test_timezone_required() -> None:
    with pytest.raises(ValueError):
        collect(clock=lambda: datetime(2026, 11, 3))


def test_explicit_host_routes() -> None:
    result = collect(
        allowed_subnets=(
            IPv4Network("192.168.34.230/32"),
            IPv4Network("192.168.34.1/32"),
        )
    )
    assert result.status == "ok"
