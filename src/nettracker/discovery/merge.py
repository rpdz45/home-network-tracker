"""Conservative merge candidates; never perform a merge automatically."""

from collections.abc import Iterable

from nettracker.db.repository import Device


def merge_candidates(candidate: Device, devices: Iterable[Device]) -> list[int]:
    """Suggest only older known devices with the same name and no overlapping history."""
    if not candidate.is_randomized_mac or candidate.status != "to_confirm":
        return []
    name = (candidate.hostname or "").strip().casefold()
    if not name:
        return []
    matches: set[int] = set()
    for device in devices:
        if device.id == candidate.id or device.status != "known":
            continue
        if device.merged_into is not None or not device.hostname:
            continue
        if device.hostname.strip().casefold() != name:
            continue
        if device.first_seen >= candidate.first_seen:
            continue
        if device.last_seen >= candidate.first_seen:
            continue
        matches.add(device.id)
    return sorted(matches)
