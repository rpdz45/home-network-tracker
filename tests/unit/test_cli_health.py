"""Tests for the health-check command."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect, migrate

BASE = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "health-test.db"\n'
CONFIG = BASE + "\n[health]\nstale_after_minutes = 5\n"
STALE_EVENTS_SQL = "SELECT COUNT(*) FROM events WHERE kind = 'collector_stale'"


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("NETTRACKER_CONFIG", "NETTRACKER_API_TOKEN", "NETTRACKER_DATABASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def write_config(directory: Path, text: str) -> None:
    (directory / "config.toml").write_text(text, encoding="utf-8")


def seed_scan(directory: Path, *, minutes_ago: int) -> None:
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    conn = connect(directory / "health-test.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        scan_id = repo.start_scan(mode="passive", started_at=started)
        repo.finish_scan(scan_id, status="ok", finished_at=started, devices_found=2)
    finally:
        conn.close()


def stale_events(directory: Path) -> int:
    conn = sqlite3.connect(directory / "health-test.db")
    try:
        row = conn.execute(STALE_EVENTS_SQL).fetchone()
    finally:
        conn.close()
    return int(row[0])


def test_recent_scan_is_healthy(isolated_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(isolated_cwd, CONFIG)
    seed_scan(isolated_cwd, minutes_ago=1)
    assert main(["health-check"]) == 0
    assert "Collector: OK" in capsys.readouterr().out
    assert stale_events(isolated_cwd) == 0


def test_stale_collector_exits_with_3_and_records_one_event(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, CONFIG)
    seed_scan(isolated_cwd, minutes_ago=60)
    assert main(["health-check"]) == 3
    output = capsys.readouterr().out
    assert "Collector: STALE" in output
    assert "no notification is sent" in output
    assert main(["health-check"]) == 3
    assert "Event collector_stale recorded" not in capsys.readouterr().out
    assert stale_events(isolated_cwd) == 1


def test_no_scan_yet_is_reported_without_failing(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, CONFIG)
    assert main(["health-check"]) == 0
    assert "no successful scan recorded yet" in capsys.readouterr().out


def test_invalid_threshold_is_rejected(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE + "\n[health]\nstale_after_minutes = 0\n")
    assert main(["health-check"]) == 1
    assert "health.stale_after_minutes" in capsys.readouterr().err


def test_check_config_shows_the_threshold(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    assert main(["check-config"]) == 0
    assert "health: stale_after_minutes=15" in capsys.readouterr().out
