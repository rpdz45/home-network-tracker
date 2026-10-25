"""Tests for the serve command (the web server itself is replaced)."""

from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

from nettracker.cli import main

BASE = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "serve-test.db"\n'


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("NETTRACKER_CONFIG", "NETTRACKER_API_TOKEN", "NETTRACKER_DATABASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def write_config(directory: Path, text: str) -> None:
    (directory / "config.toml").write_text(text, encoding="utf-8")


def test_serve_starts_the_dashboard_on_the_configured_address(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_cwd, BASE + "\n[api]\nport = 9191\n")
    assert main(["init-db"]) == 0
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(app: object, **options: object) -> None:
        calls.append((app, options))

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert main(["serve"]) == 0
    app, options = calls[0]
    assert isinstance(app, FastAPI)
    assert options["host"] == "127.0.0.1"
    assert options["port"] == 9191


def test_serve_refuses_to_start_without_a_database(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE)
    calls: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(args))
    assert main(["serve"]) == 1
    assert "init-db" in capsys.readouterr().err
    assert calls == []


def test_serve_refuses_a_lan_address_without_a_token(
    isolated_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(isolated_cwd, BASE + '\n[api]\nhost = "192.168.1.5"\n')
    assert main(["serve"]) == 1
    assert "api.token" in capsys.readouterr().err
