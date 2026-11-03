"""Storage tests with synthetic inventory; no network or user database access."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nettracker.db.network_identity import (
    NETWORK_IDENTITY_V4,
    IdentityObservation,
    current_observations,
    save_observations,
)
from nettracker.errors import DatabaseError

NOW = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)
MAC = "02:00:00:00:00:20"
IP = "192.168.34.230"
OBS = IdentityObservation("hostname", "dns_ptr", "192.168.34.1", "nas.localdomain", NOW)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "CREATE TABLE devices (id INTEGER PRIMARY KEY, mac TEXT, merged_into INTEGER, "
        "status TEXT, alias TEXT, hostname TEXT)"
    )
    connection.execute(
        "CREATE TABLE sightings (id INTEGER PRIMARY KEY, device_id INTEGER, "
        "ip TEXT, source TEXT, seen_at TEXT)"
    )
    connection.execute(
        "INSERT INTO devices VALUES (1, ?, NULL, 'known', 'Mon PC', 'ancien')", (MAC,)
    )
    connection.execute("INSERT INTO sightings VALUES (1, 1, ?, 'discovery', '2026')", (IP,))
    for statement in NETWORK_IDENTITY_V4:
        connection.execute(statement)
    yield connection
    connection.close()


def save(conn: sqlite3.Connection, *items: IdentityObservation) -> int:
    return save_observations(
        conn, device_id=1, matched_mac=MAC, matched_ip=IP,
        observations=items or (OBS,), confirmed=True, now=NOW,
    )


def test_preserves_device_and_records_source(conn: sqlite3.Connection) -> None:
    before = tuple(conn.execute("SELECT * FROM devices").fetchone())
    assert save(conn) == 1
    row = current_observations(conn, 1)[0]
    assert row["value"] == "nas.localdomain"
    assert row["source"] == "dns_ptr"
    assert row["endpoint"] == "192.168.34.1"
    assert row["retrieved_at"] == NOW.isoformat()
    assert row["stored_at"] == NOW.isoformat()
    assert tuple(conn.execute("SELECT * FROM devices").fetchone()) == before


def test_replay_is_idempotent(conn: sqlite3.Connection) -> None:
    assert save(conn) == 1
    assert save(conn) == 0
    assert len(current_observations(conn, 1)) == 1


def test_failure_keeps_previous_success(conn: sqlite3.Connection) -> None:
    assert save(conn) == 1
    failed = replace(OBS, status="timeout", value=None)
    assert save(conn, failed) == 1
    rows = current_observations(conn, 1)
    assert {row["status"] for row in rows} == {"reported", "timeout"}


@pytest.mark.parametrize("field", ["brand", "model", "device_type", "interface_vendor"])
def test_dns_cannot_claim_hardware_identity(conn: sqlite3.Connection, field: str) -> None:
    with pytest.raises(ValueError, match="DNS PTR"):
        save(conn, replace(OBS, field=field))
    assert current_observations(conn, 1) == []


def test_oui_is_not_product_brand(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="OUI"):
        save(conn, replace(OBS, source="oui", field="brand"))


def test_hardware_observations_have_independent_sources(conn: sqlite3.Connection) -> None:
    brand = replace(OBS, source="cim", field="brand", value="HP", endpoint=IP)
    model = replace(brand, field="model", value="EliteBook synthetic-test")
    interface = replace(OBS, source="oui", field="interface_vendor", value="Test adapter")
    kind = replace(brand, field="device_type", value="Laptop")
    assert save(conn, OBS, brand, model, interface, kind) == 5
    assert {row["field"] for row in current_observations(conn, 1)} == {
        "hostname", "brand", "model", "interface_vendor", "device_type",
    }


@pytest.mark.parametrize("change", ["mac", "ip", "merged", "ignored"])
def test_binding_changes_are_refused(conn: sqlite3.Connection, change: str) -> None:
    if change == "mac":
        conn.execute("UPDATE devices SET mac='02:00:00:00:00:99'")
    elif change == "ip":
        conn.execute("UPDATE sightings SET ip='192.168.34.231'")
    elif change == "merged":
        conn.execute("UPDATE devices SET merged_into=2")
    else:
        conn.execute("UPDATE devices SET status='ignored'")
    with pytest.raises(ValueError):
        save(conn)
    assert conn.execute("SELECT COUNT(*) FROM network_identity_observations").fetchone()[0] == 0


def test_old_binding_is_hidden_without_deleting_history(conn: sqlite3.Connection) -> None:
    save(conn)
    conn.execute("UPDATE sightings SET ip='192.168.34.231'")
    assert current_observations(conn, 1) == []
    assert conn.execute("SELECT COUNT(*) FROM network_identity_observations").fetchone()[0] == 1


@pytest.mark.parametrize("value", ["", " ", "a\nname", "x" * 254])
def test_invalid_values_are_refused(conn: sqlite3.Connection, value: str) -> None:
    with pytest.raises(ValueError):
        save(conn, replace(OBS, value=value))


@pytest.mark.parametrize("delta", [-1, 601])
def test_expired_and_future_evidence_is_refused(conn: sqlite3.Connection, delta: int) -> None:
    with pytest.raises(ValueError):
        save(conn, replace(OBS, retrieved_at=NOW - timedelta(seconds=delta)))


def test_caller_transaction_can_roll_back(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    assert save(conn) == 1
    conn.execute("ROLLBACK")
    assert current_observations(conn, 1) == []


def test_failed_batch_rolls_back_atomically(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TRIGGER reject_test BEFORE INSERT ON network_identity_observations "
        "WHEN NEW.value='reject.local' BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
    )
    with pytest.raises(DatabaseError):
        save(conn, OBS, replace(OBS, value="reject.local"))
    assert current_observations(conn, 1) == []


def test_confirmation_is_required(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="confirmation"):
        save_observations(
            conn, device_id=1, matched_mac=MAC, matched_ip=IP, observations=(OBS,), now=NOW,
        )


def test_invalid_endpoint_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        save(conn, replace(OBS, endpoint="https://user:secret@example.org"))


def test_naive_clock_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        save(conn, replace(OBS, retrieved_at=datetime(2026, 11, 3)))


def test_persistence_after_reopening(conn: sqlite3.Connection, tmp_path: Path) -> None:
    save(conn)
    path = tmp_path / "synthetic.db"
    with sqlite3.connect(path) as destination:
        conn.backup(destination)
    with sqlite3.connect(path) as reopened:
        reopened.row_factory = sqlite3.Row
        assert current_observations(reopened, 1)[0]["value"] == OBS.value


def test_ambiguous_ip_is_refused(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO devices VALUES (2, '02:00:00:00:00:22', NULL, 'known', '', '')")
    conn.execute("INSERT INTO sightings VALUES (2, 2, ?, 'discovery', '2026')", (IP,))
    with pytest.raises(ValueError, match="ambiguous"):
        save(conn)
    assert current_observations(conn, 1) == []


@pytest.mark.parametrize("status", ["no_record", "timeout", "unavailable", "invalid_response",
                                  "access_denied", "not_supported"])
def test_all_failure_statuses_are_recorded(conn: sqlite3.Connection, status: str) -> None:
    assert save(conn, replace(OBS, status=status, value=None)) == 1
    assert current_observations(conn, 1)[0]["status"] == status


def test_empty_batch_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="batch"):
        save_observations(
            conn, device_id=1, matched_mac=MAC, matched_ip=IP, observations=(),
            confirmed=True, now=NOW,
        )
