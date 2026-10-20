"""Explicitly enabled, bounded nmap host discovery; never run by offline tests."""

import logging
import math
import subprocess  # nosec B404
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from nettracker.db.repository import normalize_mac
from nettracker.discovery.arp import MAX_ADDRESSES, ActiveDiscoveryError
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError, require_allowed_target

logger = logging.getLogger(__name__)
MAX_XML_CHARACTERS = 1_048_576
Runner = Callable[[str, float], str]


class NmapDiscoveryError(ActiveDiscoveryError):
    """Nmap is unavailable or cannot provide usable complete observations."""


def _validate_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or not 1 <= timeout <= 120:
        raise ValueError("nmap timeout must be finite and between 1 and 120 seconds")


def _validated_target(target: str, allowed_subnets: list[IPv4Network]) -> IPv4Address | IPv4Network:
    parsed = require_allowed_target(target, allowed_subnets)
    if isinstance(parsed, IPv4Network) and parsed.num_addresses > MAX_ADDRESSES:
        raise ScopeError("nmap target exceeds the 256-address safety limit")
    return parsed


def run_nmap(target: str, timeout: float) -> str:
    """Run fixed host-discovery arguments, never shell fragments or hostnames."""
    _validate_timeout(timeout)
    private = [IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    parsed = _validated_target(target, private)
    argv = [
        "nmap",
        "-sn",
        "-n",
        "--max-rate",
        "10",
        "--max-retries",
        "1",
        "--host-timeout",
        "5s",
        "-oX",
        "-",
        str(parsed),
    ]
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603
            argv, check=True, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise NmapDiscoveryError(
            "nmap discovery unavailable: check installation, privileges and timeout"
        ) from exc
    return result.stdout


def parse_nmap_xml(text: str, target: str, allowed_subnets: list[IPv4Network]) -> list[Neighbor]:
    """Read completed XML safely; reject responses outside the authorized target."""
    parsed = _validated_target(target, allowed_subnets)
    if len(text) > MAX_XML_CHARACTERS:
        raise NmapDiscoveryError("nmap XML exceeds the size limit")
    try:
        root = fromstring(text, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ValueError, SyntaxError) as exc:
        raise NmapDiscoveryError("invalid or unsafe nmap XML") from exc
    finished = root.find("runstats/finished")
    if root.tag != "nmaprun" or finished is None or finished.get("exit") != "success":
        raise NmapDiscoveryError("nmap XML does not describe a completed successful run")
    found: dict[tuple[str, str], Neighbor] = {}
    missing_mac = 0
    for host in root.findall("host"):
        addresses = host.findall("address")
        ipv4 = [node.get("addr", "") for node in addresses if node.get("addrtype") == "ipv4"]
        for ip in ipv4:
            response = require_allowed_target(ip, allowed_subnets)
            if not isinstance(response, IPv4Address):
                raise ScopeError("nmap response is not a host address")
            if (isinstance(parsed, IPv4Network) and response not in parsed) or (
                isinstance(parsed, IPv4Address) and response != parsed
            ):
                raise ScopeError("nmap response lies outside requested target")
        status = host.find("status")
        if status is None or status.get("state") != "up" or not ipv4:
            continue
        mac_node = next((node for node in addresses if node.get("addrtype") == "mac"), None)
        try:
            mac = normalize_mac(mac_node.get("addr", "") if mac_node is not None else "")
        except ValueError:
            missing_mac += 1
            continue
        if mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1:
            missing_mac += 1
            continue
        for ip in ipv4:
            found[(ip, mac)] = Neighbor(ip, mac)
    if missing_mac:
        logger.warning("nmap omitted %s online host(s) without usable unicast MAC", missing_mac)
        if not found:
            raise NmapDiscoveryError("nmap found online hosts but no usable MAC addresses")
    return list(found.values())


def discover_nmap(
    target: str,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    runner: Runner = run_nmap,
    timeout: float = 30.0,
) -> list[Neighbor]:
    """Discover only explicitly enabled private targets; callers may inject a fake runner."""
    if not enabled:
        raise NmapDiscoveryError("nmap discovery must be explicitly enabled")
    _validate_timeout(timeout)
    parsed = _validated_target(target, allowed_subnets)
    return parse_nmap_xml(runner(str(parsed), timeout), str(parsed), allowed_subnets)
