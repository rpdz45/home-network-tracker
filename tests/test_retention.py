import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from nettracker.db.migrations import migrate
from nettracker.db.retention import count_prunable, cutoff_for, prune_ping_samples


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    migrate(connection)
    connection.execute(
        "INSERT INTO devices (id, mac, first_seen, last_seen) "
        "VALUES (1, 'aa:bb:cc:dd:ee:01', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    yield connection
    connection.close()


def _sighting(conn: sqlite3.Connection, seen_at: str, source: str) -> None:
    conn.execute(
        "INSERT INTO sightings (device_id, ip, online, seen_at, source) "
        "VALUES (1, '192.168.1.10', 1, ?, ?)",
        (seen_at, source),
    )


def _total(conn: sqlite3.Connection, source: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM sightings WHERE source = ?", (source,)).fetchone()
    return int(row[0])


def test_cutoff_requires_positive_days() -> None:
    with pytest.raises(ValueError):
        cutoff_for(datetime(2026, 10, 21, tzinfo=UTC), 0)


def test_preview_does_not_modify(conn: sqlite3.Connection) -> None:
    _sighting(conn, "2026-01-01T00:00:00+00:00", "ping")
    _sighting(conn, "2026-10-20T00:00:00+00:00", "ping")
    cutoff = cutoff_for(datetime(2026, 10, 21, tzinfo=UTC), 30)
    assert count_prunable(conn, cutoff) == 1
    assert _total(conn, "ping") == 2


def test_prune_only_old_ping_samples(conn: sqlite3.Connection) -> None:
    _sighting(conn, "2026-01-01T00:00:00+00:00", "ping")
    _sighting(conn, "2026-01-01T00:00:00+00:00", "discovery")
    _sighting(conn, "2026-10-20T00:00:00+00:00", "ping")
    cutoff = cutoff_for(datetime(2026, 10, 21, tzinfo=UTC), 30)
    assert prune_ping_samples(conn, cutoff) == 1
    assert _total(conn, "ping") == 1
    assert _total(conn, "discovery") == 1
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1


def test_prune_is_bounded_by_batches(conn: sqlite3.Connection) -> None:
    for day in range(1, 8):
        _sighting(conn, f"2026-01-0{day}T00:00:00+00:00", "ping")
    cutoff = cutoff_for(datetime(2026, 10, 21, tzinfo=UTC), 30)
    assert prune_ping_samples(conn, cutoff, batch_size=2, max_batches=2) == 4
    assert _total(conn, "ping") == 3
    assert prune_ping_samples(conn, cutoff, batch_size=2, max_batches=10) == 3
    assert _total(conn, "ping") == 0


def test_invalid_limits_are_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        prune_ping_samples(conn, "2026-01-01T00:00:00+00:00", batch_size=0)
