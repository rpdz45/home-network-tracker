"""Single bounded monitoring cycle; no daemon or implicit device enumeration."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from ipaddress import IPv4Address

from nettracker.config import Settings
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.repository import to_iso
from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import ConfigError
from nettracker.monitor.ping import PingResult, probe_ping

Probe = Callable[[str], PingResult]


def monitor_once(
    repo: MonitoringRepository,
    settings: Settings,
    device_ids: Sequence[int],
    *,
    enabled: bool = False,
    probe: Probe | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Validate all targets before the first probe; persist the whole cycle atomically."""
    if not enabled or not settings.monitor.enabled:
        raise ConfigError("monitoring requires monitor.enabled=true and --enable-monitoring")
    if not 1 <= len(device_ids) <= 64 or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in device_ids
    ):
        raise ConfigError("select between 1 and 64 positive device IDs")
    if repo.in_transaction:
        raise ConfigError("monitoring cannot run inside an open database transaction")
    targets = [repo.target(value) for value in dict.fromkeys(device_ids)]
    started = clock()
    to_iso(started)
    addresses: set[str] = set()
    for target in targets:
        parsed = require_allowed_target(target.ip, settings.allowed_subnets)
        if not isinstance(parsed, IPv4Address):
            raise ScopeError("monitoring requires single IPv4 addresses")
        if any(
            parsed in net and parsed in (net.network_address, net.broadcast_address)
            for net in settings.allowed_subnets
            if net.prefixlen < 31
        ):
            raise ScopeError("monitoring refuses configured network/broadcast addresses")
        age = (started - datetime.fromisoformat(target.observed_at)).total_seconds()
        if not 0 <= age <= settings.monitor.max_observation_age_seconds:
            raise ConfigError("discovery observation is stale or future-dated; run scan-once first")
        if target.ip in addresses:
            raise ConfigError("selected devices share an IP; refresh discovery before monitoring")
        addresses.add(target.ip)

    def actual_probe(ip: str) -> PingResult:
        return probe_ping(
            ip,
            settings.allowed_subnets,
            enabled=True,
            packets=settings.monitor.packets,
            timeout=settings.monitor.timeout_seconds,
        )

    transport = actual_probe if probe is None else probe
    # No transaction or DB lock while waiting for the subprocess.
    results = [(target, transport(target.ip)) for target in targets]
    finished = clock()
    to_iso(finished)
    if finished < started:
        raise ConfigError("monitor clock moved backwards; no measurement saved")
    with repo.transaction():
        count = sum(
            repo.record(
                target,
                online=result.online,
                latency_ms=result.latency_ms,
                packet_loss_pct=result.packet_loss_pct,
                checked_at=finished,
            )
            for target, result in results
        )
    return count
