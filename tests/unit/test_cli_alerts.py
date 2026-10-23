"""Tests for the process-alerts command."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect, migrate

BASE = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "alerts-test.db"\n'
NOTIFICATIONS_SQL = "SELECT COUNT(*) FROM notifications"


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("NETTRACKER_CONFIG", "NETTRACKER_API_TOKEN", "NETTRACKER_DATABASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def write_config(directory: Path, text: str) -> None:
    (directory / "config.toml").write_text(text, encoding="utf-8")


def seed_event(directory: Path) -> None:
    conn = connect(directory / "alerts-test.db")
    try:
        migrate(conn)
        Repository(conn).add_event("collector_stale", created_at=datetime.now(UTC))
    finally:
        conn.close()


def notifications(directory: Path) -> int:
    conn = sqlite3.connect(directory / "alerts-test.db")
    try:
        row = conn.execute(NOTIFICATIONS_SQL).fetchone()
    finally:
        conn.close()
    return int(row[0])


def test_dry_run_is_the_default_and_is_repeatable(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    seed_event(isolated_cwd)
    assert main(["process-alerts"]) == 0
    output = capsys.readouterr().out
    assert "(dry-run)" in output
    assert "1 dry-run" in output
    assert main(["process-alerts"]) == 0
    assert "0 event(s)" in capsys.readouterr().out
    assert notifications(isolated_cwd) == 1


def test_live_mode_is_refused_without_a_notifier(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE + "\n[alerts]\ndry_run = false\n")
    seed_event(isolated_cwd)
    assert main(["process-alerts"]) == 1
    assert "notifier" in capsys.readouterr().err
    assert notifications(isolated_cwd) == 0


def test_invalid_cooldown_is_rejected(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE + "\n[alerts]\ncooldown_minutes = 0\n")
    assert main(["process-alerts"]) == 1
    assert "alerts.cooldown_minutes" in capsys.readouterr().err


def test_check_config_shows_the_cooldown(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    assert main(["check-config"]) == 0
    assert "cooldown_minutes=30" in capsys.readouterr().out
