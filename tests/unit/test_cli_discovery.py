"""Test CLI discovery without touching a real neighbor cache or network."""

from pathlib import Path

import pytest

from nettracker.cli import main


def test_scan_once_uses_configured_scope_and_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "discovery.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    scopes: list[str] = []

    def fake_collect(repo: object, subnets: object) -> int:
        scopes.extend(str(subnet) for subnet in subnets)  # type: ignore[attr-defined]
        return 2

    monkeypatch.setattr("nettracker.cli.collect_passive", fake_collect)
    assert main(["scan-once", "--config", str(config)]) == 0
    assert database.exists()
    assert scopes == ["192.168.1.0/24"]
    assert "2 observation(s)" in capsys.readouterr().out


def test_active_mode_refused_before_opening_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "never-created.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n'
        '[scan]\nmode = "active"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nettracker.cli.collect_passive",
        lambda *_: pytest.fail("collector must not run in active mode"),
    )
    assert main(["scan-once", "--config", str(config)]) == 1
    assert "passive mode only" in capsys.readouterr().err
    assert not database.exists()
