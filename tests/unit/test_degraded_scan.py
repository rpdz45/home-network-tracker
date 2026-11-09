"""Degraded discovery fallback: stored on scans, read by health, shown read-only."""

import sqlite3
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.cli import main
from nettracker.config import Settings
from nettracker.db import LATEST_VERSION, Repository, connect, migrate, migrations
from nettracker.db.health import collector_health
from nettracker.discovery.collector import collect_observations
from nettracker.discovery.strategy import DiscoveryResult
from nettracker.web.app import create_app

T0 = datetime(2026, 11, 9, 12, tzinfo=UTC)
NOW = T0 + timedelta(minutes=5)
MARKER = "Dernière collecte réussie : mode dégradé"


def legacy_connection(path: Path) -> sqlite3.Connection:
    """A database frozen at schema version 3, as created before the degraded column."""
    conn = connect(path)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("nettracker.db.migrations.MIGRATIONS", migrations.MIGRATIONS[:3])
        patch.setattr("nettracker.db.migrations.LATEST_VERSION", 3)
        migrate(conn)
    return conn


def scan_columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(scans)")}


def finished_scan(repo: Repository, started_at: datetime, *, degraded: bool) -> None:
    scan_id = repo.start_scan(mode="passive", started_at=started_at, degraded=degraded)
    repo.finish_scan(scan_id, status="ok", finished_at=started_at + timedelta(seconds=1))


def settings_for(path: Path) -> Settings:
    return Settings.model_validate({"allowed_subnets": ["192.168.1.0/24"], "database_path": path})


def home_page(path: Path) -> str:
    with TestClient(create_app(settings_for(path), clock=lambda: NOW)) as client:
        response = client.get("/")
        assert response.status_code == 200
        text: str = response.text
        return text


def test_version_4_keeps_existing_scans_non_degraded(tmp_path: Path) -> None:
    conn = legacy_connection(tmp_path / "legacy.db")
    try:
        assert "degraded" not in scan_columns(conn)
        conn.execute(
            "INSERT INTO scans (started_at, mode, status) VALUES (?, 'passive', 'ok')",
            ("2026-11-09T12:00:00.000000+00:00",),
        )
        assert migrate(conn) == LATEST_VERSION
        assert "degraded" in scan_columns(conn)
        assert conn.execute("SELECT degraded FROM scans").fetchone()["degraded"] == 0
        assert migrate(conn) == LATEST_VERSION
    finally:
        conn.close()


def test_degraded_flag_only_accepts_zero_or_one(tmp_path: Path) -> None:
    conn = connect(tmp_path / "fresh.db")
    migrate(conn)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scans (started_at, mode, status, degraded) "
                "VALUES ('x', 'passive', 'ok', 2)"
            )
    finally:
        conn.close()


@pytest.mark.parametrize(("flag", "expected"), [(False, 0), (True, 1)])
def test_start_scan_records_the_flag(tmp_path: Path, flag: bool, expected: int) -> None:
    conn = connect(tmp_path / "scans.db")
    migrate(conn)
    try:
        scan_id = Repository(conn).start_scan(mode="passive", started_at=T0, degraded=flag)
        row = conn.execute("SELECT degraded FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert row["degraded"] == expected
    finally:
        conn.close()


def test_start_scan_defaults_to_not_degraded(tmp_path: Path) -> None:
    conn = connect(tmp_path / "default.db")
    migrate(conn)
    try:
        scan_id = Repository(conn).start_scan(mode="active", started_at=T0)
        row = conn.execute("SELECT degraded FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert row["degraded"] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("flag", [False, True])
def test_collect_observations_stores_the_flag(tmp_path: Path, flag: bool) -> None:
    conn = connect(tmp_path / "collect.db")
    migrate(conn)
    try:
        count = collect_observations(
            Repository(conn),
            [IPv4Network("192.168.1.0/24")],
            mode="passive",
            reader=lambda _: [],
            vendors={},
            clock=lambda: T0,
            degraded=flag,
        )
        row = conn.execute("SELECT status, degraded FROM scans").fetchone()
        assert (count, row["status"], row["degraded"]) == (0, "ok", int(flag))
    finally:
        conn.close()


def test_health_reports_the_latest_successful_scan(tmp_path: Path) -> None:
    conn = connect(tmp_path / "health.db")
    migrate(conn)
    repo = Repository(conn)
    try:
        assert collector_health(conn, NOW, 900).last_scan_degraded is None
        finished_scan(repo, T0, degraded=True)
        assert collector_health(conn, NOW, 900).last_scan_degraded is True
        failed = repo.start_scan(mode="passive", started_at=T0 + timedelta(minutes=1))
        repo.finish_scan(
            failed, status="error", finished_at=T0 + timedelta(minutes=2), error="TimeoutError"
        )
        assert collector_health(conn, NOW, 900).last_scan_degraded is True
        finished_scan(repo, T0 + timedelta(minutes=3), degraded=False)
        assert collector_health(conn, NOW, 900).last_scan_degraded is False
    finally:
        conn.close()


def test_health_tolerates_a_version_3_database(tmp_path: Path) -> None:
    conn = legacy_connection(tmp_path / "legacy-health.db")
    try:
        assert collector_health(conn, NOW, 900).last_scan_degraded is None
    finally:
        conn.close()


def test_dashboard_shows_the_degraded_mode(tmp_path: Path) -> None:
    path = tmp_path / "degraded.db"
    conn = connect(path)
    migrate(conn)
    try:
        finished_scan(Repository(conn), T0, degraded=True)
    finally:
        conn.close()
    text = home_page(path)
    assert MARKER in text
    assert "Ce n'est ni une panne de la box ni une intrusion" in text


def test_dashboard_hides_the_note_after_a_normal_scan(tmp_path: Path) -> None:
    path = tmp_path / "normal.db"
    conn = connect(path)
    migrate(conn)
    try:
        repo = Repository(conn)
        finished_scan(repo, T0, degraded=True)
        finished_scan(repo, T0 + timedelta(minutes=1), degraded=False)
    finally:
        conn.close()
    assert MARKER not in home_page(path)


def test_dashboard_still_loads_on_a_version_3_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy-web.db"
    legacy_connection(path).close()
    assert MARKER not in home_page(path)


@pytest.mark.parametrize("degraded", [False, True])
def test_scan_once_records_whether_the_fallback_was_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, degraded: bool
) -> None:
    database = tmp_path / "devices.db"
    config = tmp_path / "config.toml"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n'
        '[scan]\nmode = "active"\n',
        encoding="utf-8",
    )
    source = "system_neighbor_cache" if degraded else "active_arp"
    monkeypatch.setattr(
        "nettracker.cli.discover_with_fallback",
        lambda *args, **kwargs: DiscoveryResult([], source, degraded),
    )
    monkeypatch.setattr("nettracker.discovery.collector.load_local_registry", lambda: {})
    arguments = ["scan-once", "--config", str(config), "--enable-active"]
    assert main([*arguments, "--target", "192.168.1.0/24"]) == 0
    conn = connect(database)
    try:
        row = conn.execute("SELECT mode, degraded FROM scans").fetchone()
        expected_mode = "passive" if degraded else "active"
        assert (row["mode"], row["degraded"]) == (expected_mode, int(degraded))
    finally:
        conn.close()
