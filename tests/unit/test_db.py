"""Tests for the SQLite layer: connection, migrations and repository."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from nettracker.db import LATEST_VERSION, Repository, connect, migrate
from nettracker.errors import DatabaseError

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PHONE = "da:a1:19:00:00:01"
LAPTOP = "00:1a:2b:3c:4d:5e"
BOGUS: Any = "bogus"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "test.db")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> Repository:
    return Repository(conn)


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_migrate_creates_the_schema_and_is_idempotent(conn: sqlite3.Connection) -> None:
    expected = {"devices", "scans", "sightings", "events", "notifications", "schema_version"}
    assert expected <= table_names(conn)
    assert migrate(conn) == LATEST_VERSION
    row = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()
    assert row["n"] == LATEST_VERSION


def test_database_from_a_newer_version_is_refused(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (LATEST_VERSION + 1,))
    with pytest.raises(DatabaseError, match="newer"):
        migrate(conn)


def test_failed_migration_is_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = (("CREATE TABLE partial (x INTEGER)", "THIS IS NOT SQL"),)
    monkeypatch.setattr("nettracker.db.migrations.MIGRATIONS", broken)
    monkeypatch.setattr("nettracker.db.migrations.LATEST_VERSION", 1)
    connection = connect(tmp_path / "broken.db")
    try:
        with pytest.raises(DatabaseError, match="migration to version 1 failed"):
            migrate(connection)
        assert "partial" not in table_names(connection)
    finally:
        connection.close()


def test_corrupt_database_file_gives_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is definitely not a sqlite database" * 100)
    with pytest.raises(DatabaseError):
        connect(path)


def test_unopenable_path_gives_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DatabaseError, match="cannot open"):
        connect(tmp_path / "missing-dir" / "x.db")


def test_upsert_device_is_idempotent(repo: Repository) -> None:
    first = repo.upsert_device(LAPTOP, seen_at=T0, hostname="laptop")
    again = repo.upsert_device(LAPTOP, seen_at=T0)
    assert again.id == first.id
    assert len(repo.list_devices()) == 1
    assert again.hostname == "laptop"


def test_upsert_keeps_first_seen_and_never_moves_last_seen_back(repo: Repository) -> None:
    repo.upsert_device(LAPTOP, seen_at=T0 + timedelta(hours=1))
    earlier = repo.upsert_device(LAPTOP, seen_at=T0)
    later = repo.upsert_device(LAPTOP, seen_at=T0 + timedelta(hours=2))
    assert earlier.first_seen.startswith("2026-01-01T12:00:00")
    assert earlier.last_seen.startswith("2026-01-01T13:00:00")
    assert later.last_seen.startswith("2026-01-01T14:00:00")


def test_mac_addresses_are_normalised_so_duplicates_merge(repo: Repository) -> None:
    repo.upsert_device("00:1A:2B:3C:4D:5E", seen_at=T0)
    repo.upsert_device("00-1a-2b-3c-4d-5e", seen_at=T0)
    assert [device.mac for device in repo.list_devices()] == [LAPTOP]
    assert repo.get_device_by_mac("00-1A-2B-3C-4D-5E") is not None


@pytest.mark.parametrize("bad", ["", "zz:zz:zz:zz:zz:zz", "00:11:22:33:44", "00:11:22:33:44:55:66"])
def test_invalid_mac_is_refused(repo: Repository, bad: str) -> None:
    with pytest.raises(ValueError, match="invalid MAC"):
        repo.upsert_device(bad, seen_at=T0)


def test_naive_timestamps_are_refused(repo: Repository) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        repo.upsert_device(LAPTOP, seen_at=datetime(2026, 1, 1, 12, 0))


def test_timestamps_are_stored_in_utc(repo: Repository) -> None:
    paris = timezone(timedelta(hours=2))
    device = repo.upsert_device(LAPTOP, seen_at=datetime(2026, 1, 1, 14, 0, tzinfo=paris))
    assert device.first_seen.startswith("2026-01-01T12:00:00")
    assert device.first_seen.endswith("+00:00")


def test_randomised_macs_are_flagged(repo: Repository) -> None:
    assert repo.upsert_device(PHONE, seen_at=T0).is_randomized_mac is True
    assert repo.upsert_device(LAPTOP, seen_at=T0).is_randomized_mac is False


def test_new_devices_start_unknown_and_status_can_change(repo: Repository) -> None:
    device = repo.upsert_device(LAPTOP, seen_at=T0)
    assert device.status == "unknown"
    repo.set_status(device.id, "known")
    refreshed = repo.upsert_device(LAPTOP, seen_at=T0 + timedelta(minutes=5))
    assert refreshed.status == "known"
    assert [d.mac for d in repo.list_devices("known")] == [LAPTOP]
    assert repo.list_devices("ignored") == []


def test_status_validation_and_missing_device(repo: Repository) -> None:
    device = repo.upsert_device(LAPTOP, seen_at=T0)
    with pytest.raises(ValueError, match="device status"):
        repo.set_status(device.id, BOGUS)
    with pytest.raises(DatabaseError, match="not found"):
        repo.set_status(9999, "known")
    assert repo.get_device(9999) is None


def test_scan_lifecycle(repo: Repository, conn: sqlite3.Connection) -> None:
    scan_id = repo.start_scan(mode="passive", started_at=T0, subnet="192.168.1.0/24")
    row = conn.execute("SELECT status FROM scans WHERE id = ?", (scan_id,)).fetchone()
    assert row["status"] == "error"
    repo.finish_scan(scan_id, status="ok", finished_at=T0 + timedelta(seconds=3), devices_found=4)
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    assert (row["status"], row["devices_found"]) == ("ok", 4)
    with pytest.raises(DatabaseError, match="not found"):
        repo.finish_scan(9999, status="ok", finished_at=T0)
    with pytest.raises(ValueError, match="scan mode"):
        repo.start_scan(mode=BOGUS, started_at=T0)


def test_sightings_are_validated_and_linked_to_devices(repo: Repository) -> None:
    device = repo.upsert_device(LAPTOP, seen_at=T0)
    sighting_id = repo.add_sighting(
        device_id=device.id, ip="192.168.1.20", online=True, seen_at=T0, latency_ms=2.5
    )
    assert sighting_id > 0
    with pytest.raises(ValueError, match="does not appear"):
        repo.add_sighting(device_id=device.id, ip="nope", online=True, seen_at=T0)
    with pytest.raises(ValueError, match="packet_loss_pct"):
        repo.add_sighting(
            device_id=device.id, ip="192.168.1.20", online=True, seen_at=T0, packet_loss_pct=150
        )
    with pytest.raises(ValueError, match="latency_ms"):
        repo.add_sighting(
            device_id=device.id, ip="192.168.1.20", online=True, seen_at=T0, latency_ms=-1
        )


def test_foreign_keys_are_enforced(repo: Repository) -> None:
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        repo.add_sighting(device_id=12345, ip="192.168.1.20", online=True, seen_at=T0)


def test_events_round_trip_most_recent_first(repo: Repository) -> None:
    device = repo.upsert_device(LAPTOP, seen_at=T0)
    repo.add_event("new_device", created_at=T0, device_id=device.id, details={"ip": "192.168.1.20"})
    event_id = repo.add_event("offline", created_at=T0 + timedelta(minutes=1), device_id=device.id)
    events = repo.list_events()
    assert [event.kind for event in events] == ["offline", "new_device"]
    assert events[1].details == {"ip": "192.168.1.20"}
    assert events[0].details is None
    assert [event.id for event in repo.list_events(kind="new_device")] != [event_id]
    assert len(repo.list_events(limit=1)) == 1
    with pytest.raises(ValueError, match="event kind"):
        repo.add_event(BOGUS, created_at=T0)


def test_notifications_reference_events(repo: Repository) -> None:
    event_id = repo.add_event("collector_stale", created_at=T0)
    notification_id = repo.add_notification(
        event_id=event_id, channel="discord", status="dry_run", sent_at=T0
    )
    assert notification_id > 0
    with pytest.raises(ValueError, match="notification status"):
        repo.add_notification(event_id=event_id, channel="discord", status=BOGUS, sent_at=T0)
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        repo.add_notification(event_id=999, channel="discord", status="sent", sent_at=T0)


def test_transaction_rolls_back_on_error_and_nested_calls_join(repo: Repository) -> None:
    with pytest.raises(RuntimeError, match="boom"), repo.transaction():
        repo.upsert_device(LAPTOP, seen_at=T0)
        raise RuntimeError("boom")
    assert repo.list_devices() == []
    with repo.transaction():
        repo.upsert_device(LAPTOP, seen_at=T0)
        repo.upsert_device(PHONE, seen_at=T0)
    assert len(repo.list_devices()) == 2


def test_locked_database_raises_a_database_error(tmp_path: Path) -> None:
    path = tmp_path / "locked.db"
    first = connect(path)
    migrate(first)
    second = connect(path, timeout=0.1)
    try:
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseError, match="locked"):
            Repository(second).upsert_device(LAPTOP, seen_at=T0)
    finally:
        first.execute("ROLLBACK")
        first.close()
        second.close()
