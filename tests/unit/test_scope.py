"""Fail-closed checks without creating sockets or packets."""

from ipaddress import IPv4Address, IPv4Network

import pytest

from nettracker.discovery.scope import ScopeError, require_allowed_target

ALLOWED = [IPv4Network("192.168.1.0/24"), IPv4Network("10.7.0.0/24")]


@pytest.mark.parametrize("target", ["192.168.1.2", "10.7.0.200", "192.168.1.0/25"])
def test_accepts_explicit_private_targets(target: str) -> None:
    assert str(require_allowed_target(target, ALLOWED)) == target


@pytest.mark.parametrize(
    "target",
    [
        "8.8.8.8", "127.0.0.1", "169.254.1.1", "224.0.0.1", "192.168.2.1",
        "192.168.0.0/16", "192.168.1.4/24", "::1", "fd00::1", "router.local",
        "-sn 192.168.1.2", "", "192.168.1.0/24 --script default",
    ],
)
def test_refuses_public_other_subnet_invalid_and_ipv6(target: str) -> None:
    with pytest.raises(ScopeError):
        require_allowed_target(target, ALLOWED)


def test_rejects_empty_allowlist() -> None:
    with pytest.raises(ScopeError, match="allowed_subnets"):
        require_allowed_target("192.168.1.2", [])


def test_rejects_untrusted_allowlist() -> None:
    with pytest.raises(ScopeError, match="non-RFC1918"):
        require_allowed_target("192.168.1.2", [IPv4Network("0.0.0.0/0")])


def test_result_is_parsed_not_an_untrusted_string() -> None:
    assert isinstance(require_allowed_target("192.168.1.2", ALLOWED), IPv4Address)
