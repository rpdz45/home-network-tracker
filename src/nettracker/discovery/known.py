"""Validate explicit device trust without creating discovery targets."""

from collections.abc import Iterable

from nettracker.db.repository import normalize_mac


def normalize_known_devices(values: Iterable[str]) -> frozenset[str]:
    """Return unique unicast MACs; reject invalid or ambiguous allowlist entries."""
    if isinstance(values, (str, bytes)):
        raise ValueError("known_devices must be a collection of MAC addresses")
    result: set[str] = set()
    for value in values:
        mac = normalize_mac(value)
        if mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1:
            raise ValueError("known_devices accepts only nonzero unicast MAC addresses")
        if mac in result:
            raise ValueError("known_devices contains duplicate normalized MAC addresses")
        result.add(mac)
    return frozenset(result)
