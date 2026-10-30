"""Real SQLite storage with synthetic Fing identities and no network."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.db import connect, migrate, migrations
from nettracker.db.identifications import (
    IdentificationError,
    ImportSummary,
    get_fing_identification,
    save_fing_inventory,
)
from nettracker.discovery.fing import FingDevice, FingInventory
from nettracker.errors import DatabaseError

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
NETWORK = "192.168.1.0/24"
MAC = "02:00:00:00:00:01"


def seed(conn: sqlite3.Connection, identifier: int = 1) -> None:
    mac = MAC if identifier == 1 else "02:00:00:00:00:02"
    ip = "192.168.1.10" if identifier == 1 else "192.168.1.11"
    conn.execute(
        "INSERT INTO devices (id, mac, alias, vendor, status, first_seen, last_seen) "
        "VALUES (?, ?, 'Mon alias', 'Fabricant interface', 'to_confirm', ?, ?)",
        (identifier, mac, T0.isoformat(), T0.isoformat()),
    )
    conn.execute(
        "INSERT INTO sightings (device_id, ip, online, seen_at, source) "
        "VALUES (?, ?, 1, ?, 'discovery')",
        (identifier, ip, T0.isoformat()),
    )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "identity.db")
    migrate(connection)
    seed(connection)
    yield connection
    connection.close()


def preview(*, moment: datetime = T0, model: str | None = "Fixture model") -> FingInventory:
    return FingInventory(
        "synthetic-network",
        moment,
        (
            FingDevice(
                MAC,
                ("192.168.1.10",),
                "Fixture name",
                "Fixture brand",
                model,
                "PC",
                "UP",
            ),
        ),
        0,
    )


def save(conn: sqlite3.Connection, data: FingInventory, *, now: datetime = T0) -> ImportSummary:
    return save_fing_inventory(conn, data, [IPv4Network(NETWORK)], confirmed=True, now=now)


def test_source_dates_and_local_fields_preserved(conn: sqlite3.Connection) -> None:
    before = tuple(conn.execute("SELECT * FROM devices WHERE id=1").fetchone())
    save(conn, preview())
    row = get_fing_identification(conn, 1)
    assert row is not None
    assert row["source"] == "fing_local_api"
    assert row["verification"] == "reported"
    assert row["model"] == "Fixture model"
    assert row["matched_ip"] == "192.168.1.10"
    assert row["retrieved_at"] == row["stored_at"]
    assert tuple(conn.execute("SELECT * FROM devices WHERE id=1").fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1


def test_confirmation_required(conn: sqlite3.Connection) -> None:
    with pytest.raises(IdentificationError):
        save_fing_inventory(conn, preview(), [IPv4Network(NETWORK)], now=T0)
    assert get_fing_identification(conn, 1) is None


def test_replay_is_idempotent(conn: sqlite3.Connection) -> None:
    save(conn, preview())
    before = tuple(conn.execute("SELECT * FROM device_identifications").fetchone())
    save(conn, preview(), now=T0 + timedelta(minutes=1))
    assert tuple(conn.execute("SELECT * FROM device_identifications").fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM device_identifications").fetchone()[0] == 1


def test_newer_missing_model_does_not_keep_a_false_current_model(conn: sqlite3.Connection) -> None:
    save(conn, preview())
    later = T0 + timedelta(minutes=1)
    save(conn, preview(moment=later, model=None), now=later)
    row = get_fing_identification(conn, 1)
    assert row is not None and row["model"] is None
    save(conn, preview(), now=later)
    unchanged = get_fing_identification(conn, 1)
    assert unchanged is not None and unchanged["model"] is None


@pytest.mark.parametrize("delta", [-1, 601])
def test_future_and_expired_previews_refused(conn: sqlite3.Connection, delta: int) -> None:
    with pytest.raises(IdentificationError):
        save(conn, preview(), now=T0 + timedelta(seconds=delta))
    assert get_fing_identification(conn, 1) is None


def test_naive_timestamp_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(IdentificationError):
        save(conn, preview(moment=T0.replace(tzinfo=None)))


def test_ip_change_and_merged_device_are_not_saved(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE sightings SET ip='192.168.1.99'")
    save(conn, preview())
    assert get_fing_identification(conn, 1) is None
    conn.execute("UPDATE sightings SET ip='192.168.1.10'")
    seed(conn, 2)
    conn.execute("UPDATE devices SET merged_into=2 WHERE id=1")
    save(conn, preview())
    assert get_fing_identification(conn, 1) is None


@pytest.mark.parametrize("ip", ["8.8.8.8", "192.168.2.10", "fe80::1"])
def test_out_of_scope_preview_refused(conn: sqlite3.Connection, ip: str) -> None:
    device = FingDevice(MAC, (ip,), None, None, None, None, "UP")
    with pytest.raises(IdentificationError):
        save(conn, FingInventory("synthetic-network", T0, (device,), 0))
    assert get_fing_identification(conn, 1) is None


def test_duplicate_association_refused(conn: sqlite3.Connection) -> None:
    device = preview().devices[0]
    with pytest.raises(IdentificationError):
        save(conn, FingInventory("synthetic-network", T0, (device, device), 0))


def test_sql_failure_rolls_back_inside_outer_transaction(conn: sqlite3.Connection) -> None:
    seed(conn, 2)
    conn.execute(
        "CREATE TRIGGER reject_second BEFORE INSERT ON device_identifications "
        "WHEN NEW.device_id=2 BEGIN SELECT RAISE(ABORT, 'synthetic-private-message'); END"
    )
    other = FingDevice("02:00:00:00:00:02", ("192.168.1.11",), None, None, None, None, "UP")
    data = FingInventory("synthetic-network", T0, (preview().devices[0], other), 0)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE devices SET alias='Outer change' WHERE id=1")
    with pytest.raises(DatabaseError) as caught:
        save(conn, data)
    assert "synthetic-private-message" not in str(caught.value)
    assert conn.in_transaction
    conn.execute("COMMIT")
    assert conn.execute("SELECT COUNT(*) FROM device_identifications").fetchone()[0] == 0
    assert conn.execute("SELECT alias FROM devices WHERE id=1").fetchone()[0] == "Outer change"


def test_locked_database_is_reported(tmp_path: Path) -> None:
    first = connect(tmp_path / "locked.db")
    migrate(first)
    seed(first)
    second = connect(tmp_path / "locked.db", timeout=0.01)
    try:
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseError):
            save(second, preview())
        assert get_fing_identification(second, 1) is None
    finally:
        first.execute("ROLLBACK")
        first.close()
        second.close()


def test_v2_upgrade_preserves_devices_and_is_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "old.db")
    try:
        migrations.current_version(connection)
        migrations._apply(connection, 1, migrations.MIGRATIONS[0])
        migrations._apply(connection, 2, migrations.MIGRATIONS[1])
        seed(connection)
        before = tuple(connection.execute("SELECT * FROM devices").fetchone())
        assert migrate(connection) == migrations.LATEST_VERSION
        assert tuple(connection.execute("SELECT * FROM devices").fetchone()) == before
        assert migrate(connection) == migrations.LATEST_VERSION
        assert get_fing_identification(connection, 1) is None
    finally:
        connection.close()


def test_ping_ip_is_not_a_discovery_match(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sightings (device_id, ip, online, seen_at, source) "
        "VALUES (1, '192.168.1.99', 1, ?, 'ping')",
        ((T0 + timedelta(seconds=1)).isoformat(),),
    )
    result = save(conn, preview())
    assert result == ImportSummary(1, 0, 0)


def test_stored_evidence_is_hidden_after_mac_change(conn: sqlite3.Connection) -> None:
    save(conn, preview())
    conn.execute("UPDATE devices SET mac='02:00:00:00:00:03' WHERE id=1")
    assert get_fing_identification(conn, 1) is None


def test_reported_text_is_parameterized_not_executed(conn: sqlite3.Connection) -> None:
    reported = "'); DROP TABLE devices; --"
    save(conn, preview(model=reported))
    row = get_fing_identification(conn, 1)
    assert row is not None and row["model"] == reported
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
