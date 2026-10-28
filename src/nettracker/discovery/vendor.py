"""Offline lookup of MAC vendors from the public IEEE MA-L CSV registry."""

from collections.abc import Mapping

from nettracker.db.repository import is_locally_administered, normalize_mac
from nettracker.discovery.oui_registry import parse_ma_l_csv as parse_ma_l_csv


def lookup_vendor(mac: str, vendors: Mapping[str, str]) -> str | None:
    """Return a MA-L registrant, never infer a vendor from a locally managed MAC."""
    normalized = normalize_mac(mac)
    if is_locally_administered(normalized) or int(normalized[:2], 16) & 1:
        return None
    return vendors.get(normalized.replace(":", "")[:6].upper())
