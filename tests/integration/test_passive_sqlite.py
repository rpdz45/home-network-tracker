"""Exercise passive collection against real SQLite without network access."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError

ALLOWED = [IPv4Network("192.168.1.0/24")]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_real_sqlite_round_trip_and_repeated_discovery(tmp_path: Path) -> None:
    conn = connect(tmp_path / "passive.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        entries = [
            Neighbor("192.168.1.2", "00:11:22:33:44:55"),
            Neighbor("192.168.1.2", "00:11:22:33:44:55"),
            Neighbor("192.168.1.3", "02:11:22:33:44:66"),
        ]
        for _ in range(2):
            assert (
                collect_passive(repo, ALLOWED, reader=lambda _: entries, clock=lambda: NOW)
                == 2
            )
        assert len(repo.list_devices()) == 2
        assert [event.kind for event in repo.list_events()] == ["to_confirm", "new_device"]
        assert repo.list_devices("to_confirm")[0].mac == "02:11:22:33:44:66"
        assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 4
        assert [row[0] for row in conn.execute("SELECT status FROM scans ORDER BY id")] == [
            "ok",
            "ok",
        ]
    finally:
        conn.close()


def test_out_of_scope_reader_rolls_back_and_records_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "scope.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        entries = [
            Neighbor("192.168.1.2", "00:11:22:33:44:55"),
            Neighbor("8.8.8.8", "00:11:22:33:44:66"),
        ]
        with pytest.raises(ScopeError):
            collect_passive(repo, ALLOWED, reader=lambda _: entries, clock=lambda: NOW)
        assert repo.list_devices() == []
        assert repo.list_events() == []
        assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM scans").fetchone()[0] == "error"
    finally:
        conn.close()
