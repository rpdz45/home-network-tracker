"""Read OS neighbor caches without transmitting discovery packets."""

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_address

from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import NetTrackerError

_MAC = re.compile(r"(?i)\b([0-9a-f]{2}(?:[:-][0-9a-f]{2}){5})\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_ZERO = "00:00:00:00:00:00"
_ALLOWED_COMMANDS = {("arp", "-a"), ("ip", "-4", "neigh", "show")}


class NeighborReadError(NetTrackerError):
    """Reading the local neighbor cache failed."""


@dataclass(frozen=True)
class Neighbor:
    ip: str
    mac: str


def parse_neighbors(text: str, allowed_subnets: list[IPv4Network]) -> list[Neighbor]:
    """Parse Windows ``arp -a`` or Linux ``ip -4 neigh show`` output.

    Only entries with a valid unicast MAC and an explicitly allowed private IPv4
    address are returned. Incomplete, failed and malformed entries are ignored.
    """
    found: dict[tuple[str, str], Neighbor] = {}
    for line in text.splitlines():
        if re.search(r"(?i)\b(?:FAILED|INCOMPLETE)\b", line):
            continue
        mac_match = _MAC.search(line)
        ip_match = _IP.search(line)
        if mac_match is None or ip_match is None:
            continue
        try:
            parsed_ip = ip_address(ip_match.group())
            if parsed_ip.version != 4:
                continue
            require_allowed_target(str(parsed_ip), allowed_subnets)
        except (ValueError, ScopeError):
            continue
        mac = mac_match.group(1).replace("-", ":").lower()
        if mac == _MAC_ZERO or int(mac[:2], 16) & 1:
            continue
        neighbor = Neighbor(str(parsed_ip), mac)
        found[(neighbor.ip, neighbor.mac)] = neighbor
    return list(found.values())


Runner = Callable[[list[str], float], str]


def run_command(argv: list[str], timeout: float) -> str:
    """Execute only the two fixed neighbor-cache commands without a shell."""
    if tuple(argv) not in _ALLOWED_COMMANDS:
        raise NeighborReadError("neighbor-cache command is not allowed")
    try:
        # Command arguments are validated above; no user-controlled target or shell is used.
        result = subprocess.run(  # noqa: S603
            argv, check=True, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NeighborReadError(f"cannot read local neighbor cache: {exc}") from exc
    return result.stdout


def read_neighbors(
    allowed_subnets: list[IPv4Network],
    *,
    runner: Runner = run_command,
    platform: str | None = None,
    timeout: float = 5.0,
) -> list[Neighbor]:
    """Read cached neighbors; this never sends ARP probes or scans any subnet."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not allowed_subnets:
        raise ScopeError("allowed_subnets must not be empty")
    for subnet in allowed_subnets:
        require_allowed_target(str(subnet), allowed_subnets)
    command = ["arp", "-a"] if (platform or sys.platform) == "win32" else [
        "ip", "-4", "neigh", "show"
    ]
    return parse_neighbors(runner(command, timeout), allowed_subnets)
