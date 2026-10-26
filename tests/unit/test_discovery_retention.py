"""Retention SQL policy on a minimal SQLite fixture, without network access."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from nettracker.db.discovery_retention import retain_discovery
from nettracker.errors import ConfigError, DatabaseError

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
OLD = (NOW - timedelta(days=60)).isoformat(timespec="microseconds")
RECENT = NOW.isoformat(timespec="microseconds")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    database = sqlite3.connect(":memory:", isolation_level=None)
    database.executescript(
        "PRAGMA foreign_keys=ON;"
        "CREATE TABLE devices(id INTEGER PRIMARY KEY);"
        "INSERT INTO devices VALUES(1),(2),(3);"
        "CREATE TABLE scans(id INTEGER PRIMARY KEY, started_at TEXT, "
        "finished_at TEXT, status TEXT);"
        "CREATE TABLE sightings(id INTEGER PRIMARY KEY, device_id INTEGER REFERENCES devices(id), "
        "scan_id INTEGER REFERENCES scans(id), source TEXT, seen_at TEXT);"
    )
    try:
        yield database
    finally:
        database.close()


def observe(
    conn: sqlite3.Connection,
    identifier: int,
    device: int = 1,
    *,
    source: str = "discovery",
    moment: str = OLD,
    scan: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO sightings VALUES(?,?,?,?,?)", (identifier, device, scan, source, moment)
    )


def test_preview_is_read_only_and_apply_releases_parent_scan(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO scans VALUES(?,?,?,'ok')", [(i, OLD, OLD) for i in range(1, 9)])
    observe(conn, 1, scan=1)
    observe(conn, 2, scan=2)
    before = tuple(conn.iterdump())
    preview = retain_discovery(conn, NOW)
    assert (preview.observations, preview.scans, preview.applied) == (1, 5, False)
    assert tuple(conn.iterdump()) == before
    result = retain_discovery(conn, NOW, enabled=True)
    assert (result.observations, result.scans, result.applied) == (1, 6, True)
    assert [row[0] for row in conn.execute("SELECT id FROM scans ORDER BY id")] == [2, 8]
    assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_latest_per_device_ties_and_ping_survive(conn: sqlite3.Connection) -> None:
    observe(conn, 1)
    observe(conn, 2)
    observe(conn, 3, 2)
    observe(conn, 4, 3)
    observe(conn, 5, 3)
    observe(conn, 6, source="ping")
    result = retain_discovery(conn, NOW, enabled=True)
    assert result.observations == 2
    assert [row[0] for row in conn.execute("SELECT id FROM sightings ORDER BY id")] == [2, 3, 5, 6]


def test_success_by_time_problems_and_unfinished_scans_survive(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO scans VALUES(1,?,?,'ok')", (OLD, OLD))
    older = (NOW - timedelta(days=61)).isoformat(timespec="microseconds")
    conn.execute("INSERT INTO scans VALUES(2,?,?,'ok')", (older, older))
    conn.executemany(
        "INSERT INTO scans VALUES(?,?,?,'error')", [(i, OLD, OLD) for i in range(3, 10)]
    )
    conn.execute("INSERT INTO scans VALUES(10,?,NULL,'error')", (OLD,))
    result = retain_discovery(conn, NOW, enabled=True)
    assert result.scans == 4
    survivors = [row[0] for row in conn.execute("SELECT id FROM scans ORDER BY id")]
    assert survivors == [1, 6, 7, 8, 9, 10]


def test_bounded_batches_and_repeat_runs(conn: sqlite3.Connection) -> None:
    for identifier in range(1, 7):
        observe(conn, identifier)
    deleted = []
    for _ in range(4):
        result = retain_discovery(conn, NOW, batch_size=2, max_batches=1, enabled=True)
        deleted.append(result.observations)
    assert deleted == [2, 2, 1, 0]
    assert not conn.in_transaction


def test_cutoff_is_strict_and_latest_is_chronological(conn: sqlite3.Connection) -> None:
    observe(conn, 1)
    boundary = (NOW - timedelta(days=30)).isoformat(timespec="microseconds")
    observe(conn, 2, moment=boundary)
    observe(conn, 3, moment=RECENT)
    observe(conn, 4)
    result = retain_discovery(conn, NOW, enabled=True)
    assert result.observations == 2
    assert [row[0] for row in conn.execute("SELECT id FROM sightings ORDER BY id")] == [2, 3]


@pytest.mark.parametrize("value", [0, True, 3651])
def test_invalid_limits_never_write(conn: sqlite3.Connection, value: int) -> None:
    with pytest.raises(ConfigError):
        retain_discovery(conn, NOW, keep_days=value, enabled=True)
    assert not conn.in_transaction


def test_caller_transaction_is_not_rolled_back(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    observe(conn, 1)
    with pytest.raises(ConfigError):
        retain_discovery(conn, NOW, enabled=True)
    assert conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1
    conn.execute("ROLLBACK")


@pytest.mark.parametrize("batch_size,remaining", [(1, 3), (3, 4)])
def test_failure_rolls_back_only_current_batch(
    conn: sqlite3.Connection, batch_size: int, remaining: int
) -> None:
    for identifier in range(1, 5):
        observe(conn, identifier)
    conn.executescript(
        "CREATE TRIGGER fail_delete BEFORE DELETE ON sightings WHEN OLD.id=2 "
        "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END;"
    )
    with pytest.raises(DatabaseError):
        retain_discovery(conn, NOW, batch_size=batch_size, enabled=True)
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == remaining
    assert not conn.in_transaction


def test_foreign_keys_required(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")
    with pytest.raises(ConfigError):
        retain_discovery(conn, NOW, enabled=True)


def test_naive_clock_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ConfigError):
        retain_discovery(conn, NOW.replace(tzinfo=None), enabled=True)
