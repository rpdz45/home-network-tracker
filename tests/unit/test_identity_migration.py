"""Identity migration tests with temporary SQLite and synthetic inventory."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nettracker.db import Repository, connect, migrate, migrations
from nettracker.db.network_identity import (
    IdentityObservation,
    current_observations,
    save_observations,
)

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


def test_fresh_schema_installs_identity_storage(tmp_path: Path) -> None:
    conn = connect(tmp_path / "fresh.db")
    try:
        assert migrate(conn) == 5
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"network_identity_observations", "idx_network_identity_repeat"} <= names
        assert "idx_network_identity_device" in names
        assert migrate(conn) == 5
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 5
    finally:
        conn.close()


def test_upgrade_preserves_inventory_and_identity_after_reopening(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    conn = connect(path)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4])
            patch.setattr(migrations, "LATEST_VERSION", 4)
            assert migrate(conn) == 4
        repo = Repository(conn)
        device = repo.upsert_device("02:00:00:00:00:20", seen_at=NOW)
        scan = repo.start_scan(mode="passive", started_at=NOW, degraded=True)
        repo.add_sighting(
            device_id=device.id, ip="192.168.1.20", online=True, seen_at=NOW, scan_id=scan
        )
        repo.finish_scan(scan, status="ok", finished_at=NOW, devices_found=1)
        conn.execute("UPDATE devices SET alias = 'My NAS' WHERE id = ?", (device.id,))
        queries = (
            "SELECT * FROM devices ORDER BY id",
            "SELECT * FROM scans ORDER BY id",
            "SELECT * FROM sightings ORDER BY id",
        )
        before = [[tuple(row) for row in conn.execute(query)] for query in queries]
        assert migrate(conn) == 5
        assert [[tuple(row) for row in conn.execute(query)] for query in queries] == before
        observation = IdentityObservation("hostname", "dns_ptr", "192.168.1.1", "nas.test", NOW)
        written = save_observations(
            conn,
            device_id=device.id,
            matched_mac=device.mac,
            matched_ip="192.168.1.20",
            observations=(observation,),
            confirmed=True,
            now=NOW,
        )
        assert written == 1
        assert migrate(conn) == 5
    finally:
        conn.close()
    reopened = connect(path)
    try:
        row = current_observations(reopened, device.id)[0]
        assert (row["value"], row["endpoint"], row["source"]) == (
            "nas.test",
            "192.168.1.1",
            "dns_ptr",
        )
        assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()
