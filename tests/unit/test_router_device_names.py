"""Synthetic SQLite tests: no router traffic, migration or real user database."""

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.routers.device_names import RouterName, preview_names

MAC = "02:00:00:00:00:20"
STAMP = datetime(2026, 1, 1, tzinfo=UTC)
CREDENTIAL = secrets.token_urlsafe(24)


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(
        "CREATE TABLE devices (id INTEGER PRIMARY KEY, mac TEXT, status TEXT, "
        "merged_into INTEGER, alias TEXT);"
        "CREATE TABLE sightings (id INTEGER PRIMARY KEY, device_id INTEGER, "
        "ip TEXT, source TEXT, seen_at TEXT);"
        "INSERT INTO devices VALUES (1, '02:00:00:00:00:20', 'known', NULL, 'Mon alias');"
        "INSERT INTO sightings VALUES (1, 1, '192.168.1.20', 'discovery', '2026-01-01');"
    )
    return db


def preview(db: sqlite3.Connection, *names: RouterName) -> tuple[object, ...]:
    return preview_names(
        db,
        tuple(names),
        source="livebox5",
        endpoint="192.168.1.1",
        retrieved_at=STAMP,
        secret=CREDENTIAL,
        now=STAMP,
    )


def test_match_preserves_alias_and_provenance(conn: sqlite3.Connection) -> None:
    before = conn.total_changes
    result = preview_names(
        conn,
        (RouterName(MAC.lower(), "192.168.1.20", " Salon "),),
        source="bbox",
        endpoint="192.168.1.1",
        retrieved_at=STAMP,
        secret=CREDENTIAL,
        now=STAMP,
    )
    assert len(result) == 1
    assert result[0].name == "Salon"
    assert result[0].source == "bbox"
    assert result[0].retrieved_at == STAMP
    assert result[0].matched_mac == MAC
    assert conn.total_changes == before
    assert conn.execute("SELECT alias FROM devices").fetchone()[0] == "Mon alias"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE devices SET status = 'ignored'",
        "UPDATE devices SET merged_into = 2",
        "UPDATE sightings SET ip = '192.168.1.21'",
        "DELETE FROM sightings",
        "INSERT INTO devices VALUES (2, '02:00:00:00:00:21', 'ignored', NULL, NULL);"
        "INSERT INTO sightings VALUES (2, 2, '192.168.1.20', 'discovery', '2026-01-01')",
    ],
)
def test_unavailable_or_ambiguous_binding(conn: sqlite3.Connection, change: str) -> None:
    conn.executescript(change)
    assert preview(conn, RouterName(MAC, "192.168.1.20", "Salon")) == ()


@pytest.mark.parametrize("name", ["", " ", "x" * 129, "Salon\n", CREDENTIAL])
def test_unusable_names(conn: sqlite3.Connection, name: str) -> None:
    assert preview(conn, RouterName(MAC, "192.168.1.20", name)) == ()


@pytest.mark.parametrize(
    "other",
    [
        RouterName(MAC, "192.168.1.21", "Autre"),
        RouterName("02:00:00:00:00:21", "192.168.1.20", "Autre"),
    ],
)
def test_ambiguous_router_reports(conn: sqlite3.Connection, other: RouterName) -> None:
    assert preview(conn, RouterName(MAC, "192.168.1.20", "Salon"), other) == ()


def test_ping_does_not_change_discovery_binding(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO sightings VALUES (2, 1, '192.168.1.99', 'ping', '2026-01-02')")
    assert len(preview(conn, RouterName(MAC, "192.168.1.20", "Salon"))) == 1


@pytest.mark.parametrize("age", [-1, 601])
def test_expired_or_future_snapshot(conn: sqlite3.Connection, age: int) -> None:
    with pytest.raises(ValueError):
        preview_names(
            conn,
            (),
            source="livebox5",
            endpoint="192.168.1.1",
            retrieved_at=STAMP - timedelta(seconds=age),
            secret=CREDENTIAL,
            now=STAMP,
        )


def test_invalid_mac(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        preview(conn, RouterName("ff:ff:ff:ff:ff:ff", "192.168.1.20", "Salon"))
