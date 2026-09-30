"""Tests for the command-line interface."""

from pathlib import Path

import pytest

from nettracker import __version__
from nettracker.cli import main

CONFIG = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "cli-test.db"\n'


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("NETTRACKER_CONFIG", "NETTRACKER_API_TOKEN", "NETTRACKER_DATABASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def write_config(directory: Path, text: str = CONFIG) -> Path:
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_help_lists_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "nettracker" in output
    assert "check-config" in output
    assert "init-db" in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "COMMAND" in capsys.readouterr().out


def test_check_config_prints_a_summary(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd)
    assert main(["check-config"]) == 0
    output = capsys.readouterr().out
    assert "Configuration OK" in output
    assert "192.168.1.0/24" in output
    assert "token: not set" in output


def test_check_config_never_prints_the_token(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_cwd)
    monkeypatch.setenv("NETTRACKER_API_TOKEN", "super-private-value")
    assert main(["check-config"]) == 0
    output = capsys.readouterr().out
    assert "token: set" in output
    assert "super-private-value" not in output


def test_invalid_config_returns_an_error(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, 'allowed_subnets = ["8.8.8.0/24"]\n')
    assert main(["check-config"]) == 1
    assert "allowed_subnets" in capsys.readouterr().err


def test_missing_config_returns_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-config"]) == 1
    assert "config file not found" in capsys.readouterr().err


def test_config_option_points_to_another_file(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = isolated_cwd / "other.toml"
    other.write_text(CONFIG, encoding="utf-8")
    assert main(["check-config", "--config", str(other)]) == 0
    assert "Configuration OK" in capsys.readouterr().out


def test_init_db_creates_the_database_and_is_repeatable(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd)
    assert main(["init-db"]) == 0
    assert (isolated_cwd / "cli-test.db").exists()
    assert main(["init-db"]) == 0
    assert "schema version 1" in capsys.readouterr().out


def test_init_db_reports_database_errors(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "no/dir/x.db"\n'
    write_config(isolated_cwd, bad_path)
    assert main(["init-db"]) == 1
    assert "cannot open database" in capsys.readouterr().err
