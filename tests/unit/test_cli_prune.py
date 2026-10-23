"""Tests for the prune-history command."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect, migrate

BASE = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "prune-test.db"\n'
ENABLED = BASE + "\n[retention]\nenabled = true\nkeep_days = 30\n"
IP = "192.168.1.10"


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("NETTRACKER_CONFIG", "NETTRACKER_API_TOKEN", "NETTRACKER_DATABASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def write_config(directory: Path, text: str) -> None:
    (directory / "config.toml").write_text(text, encoding="utf-8")


def seed(directory: Path) -> None:
    """Create one old ping, one recent ping and one old non-ping sighting."""
    now = datetime.now(UTC)
    old = now - timedelta(days=60)
    conn = connect(directory / "prune-test.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device("aa:bb:cc:dd:ee:01", seen_at=now)
        old_ping = repo.add_sighting(device_id=device.id, ip=IP, online=True, seen_at=old)
        new_ping = repo.add_sighting(device_id=device.id, ip=IP, online=True, seen_at=now)
        repo.add_sighting(device_id=device.id, ip=IP, online=True, seen_at=old)
        conn.execute(
            "UPDATE sightings SET source = 'ping' WHERE id IN (?, ?)", (old_ping, new_ping)
        )
    finally:
        conn.close()


def count(directory: Path, where: str = "1 = 1") -> int:
    conn = sqlite3.connect(directory / "prune-test.db")
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM sightings WHERE {where}").fetchone()  # noqa: S608
    finally:
        conn.close()
    return int(row[0])


def test_preview_is_the_default_and_changes_nothing(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, ENABLED)
    seed(isolated_cwd)
    assert main(["prune-history"]) == 0
    output = capsys.readouterr().out
    assert "Preview only" in output
    assert "1 ping sample(s)" in output
    assert count(isolated_cwd) == 3


def test_apply_is_refused_without_retention_enabled(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    seed(isolated_cwd)
    assert main(["prune-history", "--apply"]) == 1
    assert "retention.enabled" in capsys.readouterr().err
    assert count(isolated_cwd) == 3


def test_apply_deletes_only_old_ping_samples(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, ENABLED)
    seed(isolated_cwd)
    assert main(["prune-history", "--apply"]) == 0
    assert "1 ping sample(s) deleted" in capsys.readouterr().out
    assert count(isolated_cwd) == 2
    assert count(isolated_cwd, "source = 'ping'") == 1


def test_invalid_keep_days_is_rejected(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE + "\n[retention]\nkeep_days = 0\n")
    assert main(["prune-history"]) == 1
    assert "retention.keep_days" in capsys.readouterr().err


def test_check_config_shows_retention_state(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    assert main(["check-config"]) == 0
    assert "retention: enabled=false keep_days=30" in capsys.readouterr().out
