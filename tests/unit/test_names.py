"""Reverse DNS tests use an injected lookup and never access the network."""

from ipaddress import IPv4Network

import pytest

from nettracker.discovery.names import reverse_hostname
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]


def test_disabled_never_resolves() -> None:
    assert (
        reverse_hostname(
            "192.168.1.2",
            ALLOWED,
            lookup=lambda _: pytest.fail("unexpected DNS lookup"),
        )
        is None
    )


def test_authorized_address_normalizes_returned_name() -> None:
    calls: list[str] = []

    def lookup(ip: str) -> tuple[str, list[str], list[str]]:
        calls.append(ip)
        return ("Device.Example.", [], [ip])

    assert reverse_hostname("192.168.1.2", ALLOWED, enabled=True, lookup=lookup) == (
        "device.example"
    )
    assert calls == ["192.168.1.2"]


def test_out_of_scope_and_cidr_never_resolve() -> None:
    for target in ("8.8.8.8", "192.168.1.0/24"):
        with pytest.raises(ScopeError):
            reverse_hostname(
                target,
                ALLOWED,
                enabled=True,
                lookup=lambda _: pytest.fail("unexpected DNS lookup"),
            )


def test_lookup_failure_returns_none() -> None:
    def fail(ip: str) -> tuple[str, list[str], list[str]]:
        raise OSError("simulated unavailable DNS")

    assert reverse_hostname("192.168.1.2", ALLOWED, enabled=True, lookup=fail) is None
