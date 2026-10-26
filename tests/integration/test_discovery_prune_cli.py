"""Discovery prune CLI on real project migrations; no network operation is needed."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from nettracker.config import Settings
from nettracker.db import LATEST_VERSION, Repository, connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.entrypoint import main, prune_discovery
from nettracker.errors import ConfigError, DatabaseError

OLD = datetime.now(UTC) - timedelta(days=60)


def configuration(tmp_path: Path, *, enabled: bool = False) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        'allowed_subnets = ["192.168.1.0/24"]\n'
        f"database_path = {json.dumps(str(tmp_path / 'history.db'))}\n"
        "[retention]\nenabled = true\n"
        f"[discovery_retention]\nenabled = {str(enabled).lower()}\nkeep_days = 30\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "history.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device("02:00:00:00:00:01", seen_at=OLD)
        for index in range(3):
            moment = OLD + timedelta(seconds=index)
            scan = repo.start_scan(mode="passive", started_at=moment)
            if index < 2:
                repo.add_sighting(
                    device_id=device.id,
                    scan_id=scan,
                    ip="192.168.1.20",
                    online=True,
                    seen_at=moment,
                )
            repo.finish_scan(scan, status="ok", finished_at=moment)
    finally:
        conn.close()
    return path


def test_preview_does_not_modify_data_or_target(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = connect(database)
    try:
        before = tuple(conn.iterdump())
        target = MonitoringRepository(conn).target(1)
        config = configuration(tmp_path, enabled=True)
        assert main(["prune-discovery", "--config", str(config)]) == 0
        assert "observations=1 scans=0" in capsys.readouterr().out
        assert tuple(conn.iterdump()) == before
        assert MonitoringRepository(conn).target(1) == target
    finally:
        conn.close()


def test_ping_authorization_does_not_authorize_discovery(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = configuration(tmp_path)
    assert main(["prune-discovery", "--config", str(config), "--apply"]) == 1
    assert "discovery_retention.enabled=true" in capsys.readouterr().err
    conn = connect(database)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 2
    finally:
        conn.close()


def test_apply_preserves_latest_target(database: Path, tmp_path: Path) -> None:
    conn = connect(database)
    try:
        target = MonitoringRepository(conn).target(1)
        config = configuration(tmp_path, enabled=True)
        assert main(["prune-discovery", "--config", str(config), "--apply"]) == 0
        assert MonitoringRepository(conn).target(1) == target
        assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
    finally:
        conn.close()


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    config = configuration(tmp_path)
    assert main(["prune-discovery", "--config", str(config)]) == 1
    assert not (tmp_path / "history.db").exists()


@pytest.mark.parametrize("version", [0, LATEST_VERSION + 1])
def test_incompatible_schema_is_not_migrated(database: Path, tmp_path: Path, version: int) -> None:
    conn = connect(database)
    try:
        conn.execute("UPDATE schema_version SET version=?", (version,))
        before = tuple(conn.iterdump())
        config = configuration(tmp_path, enabled=True)
        assert main(["prune-discovery", "--config", str(config), "--apply"]) == 1
        assert tuple(conn.iterdump()) == before
    finally:
        conn.close()


def test_corrupt_database_has_controlled_error(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    path.write_bytes(b"not a sqlite database")
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": str(path)}
    )
    with pytest.raises(DatabaseError):
        prune_discovery(settings)


def test_defaults_are_independent() -> None:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "retention": {"enabled": True}}
    )
    assert settings.retention.enabled
    assert not settings.discovery_retention.enabled


def test_disabled_apply_fails_before_opening_missing_database(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": str(tmp_path / "absent.db")}
    )
    with pytest.raises(ConfigError, match="discovery_retention"):
        prune_discovery(settings, apply=True)
    assert not settings.database_path.exists()


@pytest.mark.parametrize("value", [True, 0, 5001])
def test_discovery_batch_configuration_is_strict(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "allowed_subnets": ["192.168.1.0/24"],
                "discovery_retention": {"batch_size": value},
            }
        )


def test_existing_commands_are_delegated(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def existing(argv: Sequence[str] | None = None) -> int:
        seen.extend(argv or [])
        return 7

    monkeypatch.setattr("nettracker.cli.main", existing)
    assert main(["check-config"]) == 7
    assert seen == ["check-config"]


def test_root_help_mentions_discovery(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "prune-discovery" in capsys.readouterr().out
