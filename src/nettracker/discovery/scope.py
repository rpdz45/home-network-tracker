"""Fail-closed IPv4 scope checks for discovery and monitoring."""

from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network

from nettracker.config import RFC1918_NETWORKS
from nettracker.errors import NetTrackerError


class ScopeError(NetTrackerError):
    """A network target is outside the explicitly configured private scope."""


def _private_network(network: IPv4Network) -> bool:
    return any(network.subnet_of(private) for private in RFC1918_NETWORKS)


def require_allowed_target(
    target: str, allowed_subnets: list[IPv4Network]
) -> IPv4Address | IPv4Network:
    """Validate one literal IP or CIDR before passing it to any active backend.

    This function never performs DNS resolution or emits a packet. Do not pass hostnames
    or command-line fragments to network tools; callers use the returned parsed value.
    """
    if not allowed_subnets:
        raise ScopeError("allowed_subnets must not be empty")
    if any(not _private_network(network) for network in allowed_subnets):
        raise ScopeError("allowed_subnets contains a non-RFC1918 range")
    try:
        parsed = ip_network(target, strict=True) if "/" in target else ip_address(target)
    except ValueError as exc:
        raise ScopeError(f"invalid literal IPv4 target: {target!r}") from exc
    if not isinstance(parsed, (IPv4Address, IPv4Network)):
        raise ScopeError("IPv6 targets are not supported")
    if isinstance(parsed, IPv4Address):
        if not any(parsed in private for private in RFC1918_NETWORKS):
            raise ScopeError("target is not an RFC1918 private address")
        if not any(parsed in network for network in allowed_subnets):
            raise ScopeError("target is outside allowed_subnets")
    else:
        if not _private_network(parsed):
            raise ScopeError("target is not an RFC1918 private range")
        if not any(parsed.subnet_of(network) for network in allowed_subnets):
            raise ScopeError("target is outside allowed_subnets")
    return parsed
