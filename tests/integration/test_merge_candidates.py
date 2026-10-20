"""Synthetic SQLite devices for conservative merge matching, with no network."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.merge import merge_candidates

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_only_older_known_same_name_is_candidate(tmp_path: Path) -> None:
    conn = connect(tmp_path / "merge.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        old = repo.upsert_device("00:11:22:33:44:55", seen_at=NOW, hostname="Phone.Example")
        repo.set_status(old.id, "known")
        other = repo.upsert_device("00:11:22:33:44:66", seen_at=NOW, hostname="other.example")
        repo.set_status(other.id, "known")
        new = repo.upsert_device(
            "02:11:22:33:44:77",
            seen_at=NOW + timedelta(hours=1),
            hostname="phone.example",
        )
        repo.set_status(new.id, "to_confirm")
        candidate = repo.get_device(new.id)
        assert candidate is not None
        assert merge_candidates(candidate, repo.list_devices()) == [old.id]
        assert candidate.merged_into is None
        assert repo.list_events(kind="merge_suggested") == []
    finally:
        conn.close()


def test_overlapping_history_is_not_suggested(tmp_path: Path) -> None:
    conn = connect(tmp_path / "overlap.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        old = repo.upsert_device("00:11:22:33:44:55", seen_at=NOW, hostname="phone.example")
        repo.set_status(old.id, "known")
        repo.upsert_device(old.mac, seen_at=NOW + timedelta(hours=2), hostname="phone.example")
        new = repo.upsert_device(
            "02:11:22:33:44:77",
            seen_at=NOW + timedelta(hours=1),
            hostname="phone.example",
        )
        repo.set_status(new.id, "to_confirm")
        candidate = repo.get_device(new.id)
        assert candidate is not None
        assert merge_candidates(candidate, repo.list_devices()) == []
    finally:
        conn.close()
