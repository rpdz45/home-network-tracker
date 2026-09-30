"""Offline lookup of MAC vendors from the public IEEE MA-L CSV registry."""

import csv
from collections.abc import Mapping
from io import StringIO

from nettracker.db.repository import is_locally_administered, normalize_mac


def parse_ma_l_csv(text: str) -> dict[str, str]:
    """Read IEEE's Registry,Assignment,Organization Name CSV fields."""
    reader = csv.DictReader(StringIO(text))
    required = {"Registry", "Assignment", "Organization Name"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("invalid IEEE MA-L CSV header")
    vendors: dict[str, str] = {}
    for row in reader:
        if row["Registry"] != "MA-L":
            continue
        prefix = (row["Assignment"] or "").upper()
        name = (row["Organization Name"] or "").strip()
        if len(prefix) != 6 or any(char not in "0123456789ABCDEF" for char in prefix):
            continue
        if name and name.casefold() != "private":
            vendors[prefix] = name
    return vendors


def lookup_vendor(mac: str, vendors: Mapping[str, str]) -> str | None:
    """Return a MA-L registrant, never infer a vendor from a locally managed MAC."""
    normalized = normalize_mac(mac)
    if is_locally_administered(normalized) or int(normalized[:2], 16) & 1:
        return None
    return vendors.get(normalized.replace(":", "")[:6].upper())
