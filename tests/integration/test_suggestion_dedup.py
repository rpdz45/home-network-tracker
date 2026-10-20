"""Persistent suggestion deduplication with synthetic devices and no network."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.suggestions import record_merge_suggestions

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_late_name_and_old_suggestion_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "suggestions.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        old = repo.upsert_device("00:11:22:33:44:55", seen_at=NOW, hostname="fixture.example")
        repo.set_status(old.id, "known")
        later = NOW + timedelta(hours=1)
        new = repo.upsert_device("02:11:22:33:44:77", seen_at=later)
        repo.set_status(new.id, "to_confirm")
        assert record_merge_suggestions(repo, new.id, created_at=later) == 0
        repo.upsert_device(new.mac, seen_at=later, hostname="fixture.example")
        assert record_merge_suggestions(repo, new.id, created_at=later) == 1
        for index in range(101):
            repo.add_event(
                "merge_suggested",
                created_at=later,
                device_id=old.id,
                details={"candidate_device_id": 1000 + index},
            )
    finally:
        conn.close()
    reopened = connect(path)
    try:
        repo = Repository(reopened)
        assert record_merge_suggestions(repo, new.id, created_at=later) == 0
        events = repo.list_events(kind="merge_suggested", limit=-1)
        assert len([event for event in events if event.device_id == new.id]) == 1
        device = repo.get_device(new.id)
        assert device is not None
        assert device.status == "to_confirm"
        assert device.merged_into is None
        assert reopened.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
    finally:
        reopened.close()
