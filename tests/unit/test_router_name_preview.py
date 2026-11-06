"""Read-only preview tests use temporary synthetic databases and snapshots."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nettracker.routers.bbox_session import BboxHost, BboxSnapshot
from nettracker.routers.livebox5 import LiveboxSnapshot
from nettracker.web.router_name_preview import preview_snapshot

MAC = "02:00:00:00:00:20"


def inventory(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "CREATE TABLE devices (id INTEGER PRIMARY KEY, mac TEXT, status TEXT, "
            "merged_into INTEGER, alias TEXT);"
            "CREATE TABLE sightings (id INTEGER PRIMARY KEY, device_id INTEGER, "
            "ip TEXT, source TEXT, seen_at TEXT);"
            "INSERT INTO devices VALUES (1, '02:00:00:00:00:20', 'known', NULL, 'Mon alias');"
            "INSERT INTO sightings VALUES (1, 1, '192.168.1.20', 'discovery', '2026-01-01');"
        )
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["livebox5", "bbox"])
def test_preview_preserves_database(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "inventory.db"
    inventory(path)
    before = path.read_bytes()
    snapshot: LiveboxSnapshot | BboxSnapshot
    if kind == "livebox5":
        snapshot = LiveboxSnapshot(
            "Livebox 5", None,
            ({"PhysAddress": MAC, "IPAddress": "192.168.1.20", "Name": "Salon"},),
        )
    else:
        snapshot = BboxSnapshot(
            "synthetic", None,
            (BboxHost(1, "Salon", "192.168.1.20", MAC, True, None),), True,
        )
    candidates, unavailable = preview_snapshot(
        path, snapshot, "https://192.168.1.1", "synthetic-credential", datetime.now(UTC)
    )
    assert not unavailable
    assert len(candidates) == 1
    assert candidates[0].device_id == 1
    assert candidates[0].name == "Salon"
    assert candidates[0].source == kind
    assert path.read_bytes() == before


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    result = preview_snapshot(
        path, LiveboxSnapshot("Livebox 5", None, ()),
        "https://192.168.1.1", "synthetic-credential", datetime.now(UTC),
    )
    assert result == ((), True)
    assert not path.exists()


def test_invalid_snapshot_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    result = preview_snapshot(
        path, LiveboxSnapshot("Livebox 5", None, ({"Name": "Salon"},)),
        "https://192.168.1.1", "synthetic-credential", datetime.now(UTC),
    )
    assert result == ((), True)
    assert not path.exists()


def test_unprepared_database_is_not_migrated(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    conn = sqlite3.connect(path)
    conn.close()
    before = path.read_bytes()
    result = preview_snapshot(
        path, LiveboxSnapshot("Livebox 5", None, ()),
        "https://192.168.1.1", "synthetic-credential", datetime.now(UTC),
    )
    assert result == ((), True)
    assert path.read_bytes() == before
