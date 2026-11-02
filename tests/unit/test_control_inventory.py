"""In-memory SQLite evidence only; never contact a router."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.db.control_inventory import resolve_control_target
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository
from nettracker.routers.control import AccessControlError, RouterKind

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrate(connection)
    yield connection
    connection.close()


def observe(
    conn: sqlite3.Connection,
    *,
    mac: str = "02:00:00:00:00:20",
    ip: str = "192.168.1.20",
    age: int = 0,
    online: bool = True,
) -> int:
    repo = Repository(conn)
    stamp = NOW - timedelta(seconds=age)
    device = repo.upsert_device(mac, seen_at=stamp)
    repo.add_sighting(device_id=device.id, ip=ip, online=online, seen_at=stamp)
    return device.id


def resolve(conn: sqlite3.Connection, device_id: int) -> str:
    request = resolve_control_target(
        conn,
        device_id,
        True,
        router=RouterKind.LIVEBOX5,
        now=NOW,
        max_age=timedelta(seconds=60),
    )
    assert request.mac == "02:00:00:00:00:20"
    assert request.blocked is True
    return str(request.address)


def test_fresh_target_and_boundary(conn: sqlite3.Connection) -> None:
    device_id = observe(conn, age=60)
    assert resolve(conn, device_id) == "192.168.1.20"


@pytest.mark.parametrize("age", [61, -1])
def test_stale_or_future(conn: sqlite3.Connection, age: int) -> None:
    device_id = observe(conn, age=age)
    with pytest.raises(AccessControlError):
        resolve(conn, device_id)


def test_missing_merged_and_offline(conn: sqlite3.Connection) -> None:
    with pytest.raises(AccessControlError):
        resolve(conn, 999)
    device_id = observe(conn, online=False)
    with pytest.raises(AccessControlError):
        resolve(conn, device_id)
    other = observe(conn, mac="02:00:00:00:00:21", ip="192.168.1.21")
    conn.execute("UPDATE devices SET merged_into = ? WHERE id = ?", (other, device_id))
    with pytest.raises(AccessControlError, match="merged"):
        resolve(conn, device_id)


def test_changed_ip_and_shared_ip(conn: sqlite3.Connection) -> None:
    device_id = observe(conn, age=10)
    observe(conn, ip="192.168.1.21")
    with pytest.raises(AccessControlError, match="ambiguous"):
        resolve(conn, device_id)
    conn.execute("DELETE FROM sightings WHERE ip = ?", ("192.168.1.21",))
    observe(conn, mac="02:00:00:00:00:21")
    with pytest.raises(AccessControlError, match="ownership"):
        resolve(conn, device_id)


def test_ping_and_ipv6_are_not_target_evidence(conn: sqlite3.Connection) -> None:
    device_id = observe(conn)
    conn.execute("UPDATE sightings SET source = 'ping'")
    with pytest.raises(AccessControlError, match="discovery"):
        resolve(conn, device_id)
    observe(conn, ip="fd00::20")
    with pytest.raises(AccessControlError, match="IPv4"):
        resolve(conn, device_id)


def test_database_error_is_sanitized(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE sightings")
    with pytest.raises(AccessControlError, match="unavailable"):
        resolve(conn, 1)
