"""Identity schema integration on temporary databases, without network access."""

import sqlite3
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
MAC = "02:00:00:00:00:20"
IP = "192.168.1.20"


def test_fresh_schema_installs_identity_storage(tmp_path: Path) -> None:
    conn = connect(tmp_path / "fresh.db")
    try:
        assert migrate(conn) == 5
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "network_identity_observations" in tables
        assert "idx_network_identity_device" in tables
        assert "idx_network_identity_repeat" in tables
        assert migrate(conn) == 5
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 5
    finally:
        conn.close()


def test_upgrade_preserves_inventory_and_supports_identity_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    conn = connect(path)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4])
            patch.setattr(migrations, "LATEST_VERSION", 4)
            assert migrate(conn) == 4
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW)
        scan_id = repo.start_scan(mode="passive", started_at=NOW, degraded=True)
        repo.add_sighting(device_id=device.id, ip=IP, online=True, seen_at=NOW, scan_id=scan_id)
        repo.finish_scan(scan_id, status="ok", finished_at=NOW, devices_found=1)
        conn.execute("UPDATE devices SET alias = 'My NAS' WHERE id = ?", (device.id,))
        before = {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("devices", "scans", "sightings")
        }
        assert migrate(conn) == 5
        for table, rows in before.items():
            after = [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            assert after == rows
        observation = IdentityObservation("hostname", "dns_ptr", "192.168.1.1", "nas.test", NOW)
        arguments = {
            "device_id": device.id,
            "matched_mac": MAC,
            "matched_ip": IP,
            "observations": (observation,),
            "confirmed": True,
            "now": NOW,
        }
        assert save_observations(
            conn,
            device_id=device.id,
            matched_mac=MAC,
            matched_ip=IP,
            observations=(observation,),
            confirmed=True,
            now=NOW,
        ) == 1
        assert current_observations(conn, device.id)[0]["value"] == "nas.test"
        assert arguments["matched_ip"] == IP
        assert migrate(conn) == 5
    finally:
        conn.close()
    reopened = connect(path)
    try:
        row = current_observations(reopened, device.id)[0]
        assert (row["source"], row["endpoint"], row["value"]) == (
            "dns_ptr",
            "192.168.1.1",
            "nas.test",
        )
        assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()
