"""Opt-in reverse DNS lookup for explicitly scoped IPv4 devices."""

import socket
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network

from nettracker.discovery.scope import ScopeError, require_allowed_target

Lookup = Callable[[str], tuple[str, list[str], list[str]]]


def reverse_hostname(
    ip: str,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    lookup: Lookup = socket.gethostbyaddr,
) -> str | None:
    """Resolve only an explicitly authorized host when the caller opts in."""
    if not enabled:
        return None
    target = require_allowed_target(ip, allowed_subnets)
    if not isinstance(target, IPv4Address):
        raise ScopeError("reverse DNS requires an IPv4 host, not a CIDR")
    try:
        name, _, _ = lookup(str(target))
    except OSError:
        return None
    return name.rstrip(".").casefold() or None
