"""Additive identity schema migration on temporary SQLite, without network access."""

import sqlite3
from collections.abc import Iterator

import pytest

from nettracker.db import migrations
from nettracker.db.network_identity import NETWORK_IDENTITY_V4
from nettracker.errors import DatabaseError


@pytest.fixture
def legacy() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    migrations.current_version(conn)
    for version, statements in enumerate(migrations.MIGRATIONS[:3], start=1):
        migrations._apply(conn, version, statements)
    conn.execute(
        "INSERT INTO devices (id, mac, alias, status, first_seen, last_seen) "
        "VALUES (1, '02:00:00:00:00:01', 'Alias conserve', 'known', 't0', 't0')"
    )
    conn.execute(
        "INSERT INTO sightings (device_id, ip, online, seen_at, source) "
        "VALUES (1, '192.168.34.230', 1, 't0', 'discovery')"
    )
    conn.execute(
        "INSERT INTO device_identifications (device_id, source, network_id, matched_mac, "
        "matched_ip, reported_name, retrieved_at, stored_at) VALUES "
        "(1, 'fing_local_api', 'synthetic', '02:00:00:00:00:01', "
        "'192.168.34.230', 'Nom Fing conserve', 't0', 't0')"
    )
    yield conn
    conn.close()


def test_upgrade_preserves_inventory_and_fing(legacy: sqlite3.Connection) -> None:
    statements = (
        "SELECT * FROM devices",
        "SELECT * FROM sightings",
        "SELECT * FROM device_identifications",
    )
    before = [legacy.execute(statement).fetchall() for statement in statements]
    assert migrations.migrate(legacy) == migrations.LATEST_VERSION
    after = [legacy.execute(statement).fetchall() for statement in statements]
    assert after == before
    assert legacy.execute("SELECT COUNT(*) FROM network_identity_observations").fetchone()[0] == 0


def test_new_migration_is_registered(legacy: sqlite3.Connection) -> None:
    assert migrations.MIGRATIONS[3] == NETWORK_IDENTITY_V4
    assert migrations.migrate(legacy) == migrations.LATEST_VERSION


def test_upgrade_is_idempotent(legacy: sqlite3.Connection) -> None:
    migrations.migrate(legacy)
    count = legacy.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    migrations.migrate(legacy)
    assert legacy.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == count


def test_failed_migration_is_atomic(
    legacy: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = (*migrations.MIGRATIONS[:3], (*NETWORK_IDENTITY_V4, "INVALID SQL"))
    monkeypatch.setattr(migrations, "MIGRATIONS", broken)
    monkeypatch.setattr(migrations, "LATEST_VERSION", len(broken))
    with pytest.raises(DatabaseError, match="migration"):
        migrations.migrate(legacy)
    assert legacy.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 3
    table_count = legacy.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='network_identity_observations'"
    ).fetchone()[0]
    assert table_count == 0
    assert legacy.execute("SELECT alias FROM devices WHERE id=1").fetchone()[0] == "Alias conserve"


def test_readonly_database_is_not_migrated(legacy: sqlite3.Connection) -> None:
    legacy.execute("PRAGMA query_only=ON")
    with pytest.raises(DatabaseError):
        migrations.migrate(legacy)
    assert legacy.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 3


def test_fresh_database_gets_identity_table() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        assert migrations.migrate(conn) == migrations.LATEST_VERSION
        assert conn.execute("SELECT COUNT(*) FROM network_identity_observations").fetchone()[0] == 0
    finally:
        conn.close()
