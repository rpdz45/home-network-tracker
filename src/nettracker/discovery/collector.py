"""Coordinate one passive discovery cycle and persist its results."""

from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv4Network

from nettracker.db.repository import Repository
from nettracker.discovery.passive import Neighbor, read_neighbors
from nettracker.discovery.scope import require_allowed_target

Clock = Callable[[], datetime]
Reader = Callable[[list[IPv4Network]], list[Neighbor]]


def collect_passive(
    repo: Repository,
    allowed_subnets: list[IPv4Network],
    *,
    reader: Reader = read_neighbors,
    clock: Clock = lambda: datetime.now(UTC),
) -> int:
    """Read and store neighbor cache once; return count of distinct device observations.

    A failure is recorded as an unsuccessful scan and re-raised. No active discovery
    backend is called. Caller must first initialize/migrate the database.
    """
    if not allowed_subnets:
        raise ValueError("allowed_subnets must not be empty")
    scan_id = repo.start_scan(mode="passive", started_at=clock())
    try:
        neighbors = reader(allowed_subnets)
        with repo.transaction():
            count = 0
            seen: set[tuple[str, str]] = set()
            for neighbor in neighbors:
                require_allowed_target(neighbor.ip, allowed_subnets)
                key = (neighbor.mac.lower(), neighbor.ip)
                if key in seen:
                    continue
                seen.add(key)
                device = repo.get_device_by_mac(neighbor.mac)
                new = device is None
                device = repo.upsert_device(neighbor.mac, seen_at=clock())
                if new:
                    kind = "to_confirm" if device.is_randomized_mac else "new_device"
                    if device.is_randomized_mac:
                        repo.set_status(device.id, "to_confirm")
                    repo.add_event(kind, created_at=clock(), device_id=device.id)
                repo.add_sighting(
                    device_id=device.id,
                    scan_id=scan_id,
                    ip=neighbor.ip,
                    online=True,
                    seen_at=clock(),
                )
                count += 1
            repo.finish_scan(scan_id, status="ok", finished_at=clock(), devices_found=count)
        return count
    except Exception as exc:
        repo.finish_scan(scan_id, status="error", finished_at=clock(), error=type(exc).__name__)
        raise
