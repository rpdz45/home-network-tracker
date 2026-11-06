"""Pure snapshot conversion; no router requests, persistence or alias changes."""

from typing import TYPE_CHECKING

from nettracker.routers.device_names import MAX_NAMES, RouterName, _mac

if TYPE_CHECKING:
    from nettracker.routers.bbox_session import BboxSnapshot
    from nettracker.routers.livebox5 import LiveboxSnapshot

from ipaddress import IPv4Address


def _report(mac: object, ip: object, name: object) -> RouterName:
    if not isinstance(mac, str) or not isinstance(ip, str):
        raise ValueError("router report requires a MAC and an IPv4 address")
    normalized_mac = _mac(mac)
    try:
        normalized_ip = str(IPv4Address(ip))
    except ValueError:
        raise ValueError("router report requires a valid IPv4 address") from None
    return RouterName(normalized_mac, normalized_ip, name if isinstance(name, str) else "")


def livebox_names(snapshot: "LiveboxSnapshot") -> tuple[RouterName, ...]:
    """Convert a supplied snapshot without collecting or inferring presence.

    Missing or malformed bindings reject the entire batch. Unnamed and duplicate
    bindings remain in the result so preview_names can exclude ambiguities.
    """
    if len(snapshot.devices) > MAX_NAMES:
        raise ValueError("router name batch exceeds the limit")
    return tuple(
        _report(device.get("PhysAddress"), device.get("IPAddress"), device.get("Name"))
        for device in snapshot.devices
    )


def bbox_names(snapshot: "BboxSnapshot") -> tuple[RouterName, ...]:
    """Convert host bindings, preserving duplicates and unnamed hosts."""
    if len(snapshot.hosts) > MAX_NAMES:
        raise ValueError("router name batch exceeds the limit")
    return tuple(_report(host.mac, host.address, host.name) for host in snapshot.hosts)
