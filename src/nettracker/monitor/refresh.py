"""Opt-in cache refresh for selected monitors; never an active discovery backend."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from ipaddress import IPv4Address

from nettracker.config import Settings
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.repository import normalize_mac, to_iso
from nettracker.discovery.collector import Reader, collect_passive
from nettracker.discovery.known import normalize_known_devices
from nettracker.discovery.passive import Neighbor, read_neighbors
from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import ConfigError, DatabaseError

MAX_CACHE_ENTRIES = 4096


def refresh_selected(
    repo: MonitoringRepository,
    settings: Settings,
    device_ids: Sequence[int],
    *,
    enabled: bool = False,
    reader: Reader | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Validate one cache snapshot before persisting only selected device observations."""
    if not enabled or not settings.monitor.enabled:
        raise ConfigError("passive monitor refresh requires explicit monitoring activation")
    if settings.scan.mode != "passive":
        raise ConfigError("passive monitor refresh requires scan.mode=passive")
    if not 1 <= len(device_ids) <= 64 or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in device_ids
    ):
        raise ConfigError("select between 1 and 64 positive device IDs")
    if repo.in_transaction:
        raise ConfigError("passive monitor refresh cannot run inside a database transaction")
    selected: set[str] = set()
    for device_id in dict.fromkeys(device_ids):
        device = repo.get_device(device_id)
        if device is None or device.status == "ignored" or device.merged_into is not None:
            raise DatabaseError("refresh target must exist and be unmerged and non-ignored")
        selected.add(device.mac)

    transport = read_neighbors if reader is None else reader
    snapshot = transport(settings.allowed_subnets)
    if len(snapshot) > MAX_CACHE_ENTRIES:
        raise ConfigError("passive cache exceeds the 4096-entry refresh limit")
    by_mac: dict[str, set[str]] = {}
    by_ip: dict[str, set[str]] = {}
    observations: list[Neighbor] = []
    for neighbor in snapshot:
        parsed = require_allowed_target(neighbor.ip, settings.allowed_subnets)
        if not isinstance(parsed, IPv4Address):
            raise ScopeError("passive monitor refresh requires single IPv4 addresses")
        if any(
            parsed in net and parsed in (net.network_address, net.broadcast_address)
            for net in settings.allowed_subnets
            if net.prefixlen < 31
        ):
            raise ScopeError("passive monitor refresh refuses network/broadcast addresses")
        try:
            mac = normalize_mac(neighbor.mac)
            normalize_known_devices((mac,))
        except ValueError as exc:
            raise ConfigError("passive cache contains an invalid unicast MAC") from exc
        ip = str(parsed)
        by_mac.setdefault(mac, set()).add(ip)
        by_ip.setdefault(ip, set()).add(mac)
        if mac in selected:
            observations.append(Neighbor(ip, mac))
    for mac in selected:
        addresses = by_mac.get(mac, set())
        if len(addresses) != 1:
            raise ConfigError("selected MAC is missing or has ambiguous cache addresses")
        if len(by_ip[next(iter(addresses))]) != 1:
            raise ConfigError("selected IP has ambiguous cache owners")

    moment = clock()
    to_iso(moment)
    return collect_passive(
        repo,
        settings.allowed_subnets,
        reader=lambda _: observations,
        clock=lambda: moment,
    )
