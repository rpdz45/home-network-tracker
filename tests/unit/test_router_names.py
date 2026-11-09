"""Real SQLite storage with synthetic router names and no network."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from nettracker.db import connect, migrate, migrations
from nettracker.db.router_names import (
    RouterNameError,
    SaveSummary,
    get_router_names,
    save_router_names,
)
from nettracker.errors import DatabaseError
from nettracker.routers.device_names import NameCandidate

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
MAC = "02:00:00:00:00:01"
CANDIDATE = NameCandidate(1, MAC, "192.168.1.10", "Salon", "livebox5", "192.168.1.1", T0)


def seed(conn: sqlite3.Connection, identifier: int = 1) -> None:
    mac = MAC if identifier == 1 else f"02:00:00:00:00:0{identifier}"
    ip = f"192.168.1.{9 + identifier}"
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
    connection = connect(tmp_path / "names.db")
    migrate(connection)
    seed(connection)
    yield connection
    connection.close()


def save(conn: sqlite3.Connection, *items: NameCandidate, now: datetime = T0) -> SaveSummary:
    return save_router_names(conn, items, confirmed=True, now=now)


def count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM router_name_observations").fetchone()[0])


def test_name_dates_and_local_fields_preserved(conn: sqlite3.Connection) -> None:
    before = tuple(conn.execute("SELECT * FROM devices WHERE id=1").fetchone())
    assert save(conn, CANDIDATE) == SaveSummary(1, 0, 0)
    rows = get_router_names(conn, 1)
    assert len(rows) == 1
    assert rows[0]["source"] == "livebox5"
    assert rows[0]["reported_name"] == "Salon"
    assert rows[0]["endpoint"] == "192.168.1.1"
    assert rows[0]["matched_ip"] == "192.168.1.10"
    assert rows[0]["retrieved_at"] == rows[0]["stored_at"]
    assert tuple(conn.execute("SELECT * FROM devices WHERE id=1").fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1


def test_confirmation_required(conn: sqlite3.Connection) -> None:
    with pytest.raises(RouterNameError):
        save_router_names(conn, (CANDIDATE,), now=T0)
    assert count(conn) == 0


def test_replay_is_idempotent(conn: sqlite3.Connection) -> None:
    save(conn, CANDIDATE)
    before = tuple(conn.execute("SELECT * FROM router_name_observations").fetchone())
    assert save(conn, CANDIDATE, now=T0 + timedelta(minutes=1)) == SaveSummary(0, 0, 1)
    assert tuple(conn.execute("SELECT * FROM router_name_observations").fetchone()) == before
    assert count(conn) == 1


def test_newer_name_replaces_and_older_does_not(conn: sqlite3.Connection) -> None:
    later = T0 + timedelta(minutes=1)
    save(conn, CANDIDATE)
    newer = replace(CANDIDATE, name="Cuisine", retrieved_at=later)
    assert save(conn, newer, now=later) == SaveSummary(1, 0, 0)
    assert save(conn, CANDIDATE, now=later) == SaveSummary(0, 0, 1)
    rows = get_router_names(conn, 1)
    assert [row["reported_name"] for row in rows] == ["Cuisine"]


def test_both_boxes_coexist_for_one_device(conn: sqlite3.Connection) -> None:
    other = replace(CANDIDATE, name="Bureau", source="bbox", endpoint="192.168.1.254")
    assert save(conn, CANDIDATE, other) == SaveSummary(2, 0, 0)
    rows = get_router_names(conn, 1)
    assert [(row["source"], row["reported_name"]) for row in rows] == [
        ("bbox", "Bureau"),
        ("livebox5", "Salon"),
    ]


@pytest.mark.parametrize("delta", [-1, 601])
def test_future_and_expired_previews_refused(conn: sqlite3.Connection, delta: int) -> None:
    with pytest.raises(RouterNameError):
        save(conn, CANDIDATE, now=T0 + timedelta(seconds=delta))
    assert count(conn) == 0


def test_naive_timestamp_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(RouterNameError):
        save(conn, replace(CANDIDATE, retrieved_at=T0.replace(tzinfo=None)))


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "unknown"},
        {"name": ""},
        {"name": " Salon"},
        {"name": "Salon\n"},
        {"name": "x" * 129},
        {"matched_mac": "02:00:00:00:00:AA"},
        {"matched_mac": "01:00:00:00:00:01"},
        {"matched_mac": "00:00:00:00:00:00"},
        {"endpoint": "box.local"},
        {"matched_ip": "fe80::1"},
        {"device_id": 0},
        {"device_id": True},
    ],
)
def test_invalid_candidates_refused(conn: sqlite3.Connection, changes: dict[str, Any]) -> None:
    with pytest.raises(RouterNameError):
        save(conn, replace(CANDIDATE, **changes))
    assert count(conn) == 0


@pytest.mark.parametrize(
    "batch",
    [(), (CANDIDATE, CANDIDATE), (CANDIDATE,) * 513],
)
def test_invalid_batches_refused(
    conn: sqlite3.Connection, batch: tuple[NameCandidate, ...]
) -> None:
    with pytest.raises(RouterNameError):
        save(conn, *batch)
    assert count(conn) == 0


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE sightings SET ip='192.168.1.99'",
        "UPDATE devices SET status='ignored'",
        "UPDATE devices SET mac='02:00:00:00:00:03'",
        "DELETE FROM sightings",
    ],
)
def test_changed_binding_is_not_saved(conn: sqlite3.Connection, change: str) -> None:
    conn.execute(change)
    assert save(conn, CANDIDATE) == SaveSummary(0, 1, 0)
    assert count(conn) == 0


def test_merged_device_is_not_saved(conn: sqlite3.Connection) -> None:
    seed(conn, 2)
    conn.execute("UPDATE devices SET merged_into=2 WHERE id=1")
    assert save(conn, CANDIDATE) == SaveSummary(0, 1, 0)
    assert count(conn) == 0


def test_ambiguous_recorded_address_is_not_saved(conn: sqlite3.Connection) -> None:
    seed(conn, 2)
    conn.execute("UPDATE sightings SET ip='192.168.1.10' WHERE device_id=2")
    assert save(conn, CANDIDATE) == SaveSummary(0, 1, 0)
    assert count(conn) == 0


def test_ping_ip_is_not_a_discovery_match(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sightings (device_id, ip, online, seen_at, source) "
        "VALUES (1, '192.168.1.99', 1, ?, 'ping')",
        ((T0 + timedelta(seconds=1)).isoformat(),),
    )
    assert save(conn, CANDIDATE) == SaveSummary(1, 0, 0)


def test_stored_evidence_is_hidden_after_mac_change_or_merge(conn: sqlite3.Connection) -> None:
    save(conn, CANDIDATE)
    conn.execute("UPDATE devices SET mac='02:00:00:00:00:03' WHERE id=1")
    assert get_router_names(conn, 1) == []
    conn.execute("UPDATE devices SET mac=?, merged_into=1 WHERE id=1", (MAC,))
    assert get_router_names(conn, 1) == []


def test_reported_text_is_parameterized_not_executed(conn: sqlite3.Connection) -> None:
    reported = "'); DROP TABLE devices; --"
    save(conn, replace(CANDIDATE, name=reported))
    rows = get_router_names(conn, 1)
    assert rows[0]["reported_name"] == reported
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1


def test_sql_failure_rolls_back_inside_outer_transaction(conn: sqlite3.Connection) -> None:
    seed(conn, 2)
    conn.execute(
        "CREATE TRIGGER reject_second BEFORE INSERT ON router_name_observations "
        "WHEN NEW.device_id=2 BEGIN SELECT RAISE(ABORT, 'synthetic-private-message'); END"
    )
    other = replace(
        CANDIDATE, device_id=2, matched_mac="02:00:00:00:00:02", matched_ip="192.168.1.11"
    )
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE devices SET alias='Outer change' WHERE id=1")
    with pytest.raises(DatabaseError) as caught:
        save(conn, CANDIDATE, other)
    assert "synthetic-private-message" not in str(caught.value)
    assert conn.in_transaction
    conn.execute("COMMIT")
    assert count(conn) == 0
    assert conn.execute("SELECT alias FROM devices WHERE id=1").fetchone()[0] == "Outer change"


def test_locked_database_is_reported(tmp_path: Path) -> None:
    first = connect(tmp_path / "locked.db")
    migrate(first)
    seed(first)
    second = connect(tmp_path / "locked.db", timeout=0.01)
    try:
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseError):
            save(second, CANDIDATE)
        assert get_router_names(second, 1) == []
    finally:
        first.execute("ROLLBACK")
        first.close()
        second.close()


def test_schema_rejects_unknown_source_and_empty_name(conn: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO router_name_observations (device_id, source, endpoint, matched_mac, "
        "matched_ip, reported_name, retrieved_at, stored_at) "
        "VALUES (1, ?, '192.168.1.1', ?, '192.168.1.10', ?, 'a', 'b')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("fing_local_api", MAC, "Salon"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("bbox", MAC, ""))


def test_v3_upgrade_preserves_devices_and_is_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "old.db")
    try:
        migrations.current_version(connection)
        for number in (1, 2, 3):
            migrations._apply(connection, number, migrations.MIGRATIONS[number - 1])
        seed(connection)
        before = tuple(connection.execute("SELECT * FROM devices").fetchone())
        assert migrate(connection) == migrations.LATEST_VERSION
        assert tuple(connection.execute("SELECT * FROM devices").fetchone()) == before
        assert migrate(connection) == migrations.LATEST_VERSION
        assert get_router_names(connection, 1) == []
    finally:
        connection.close()
