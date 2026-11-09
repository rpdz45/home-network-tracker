"""Tests for the Discord notifier and its configuration. No real network access."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from nettracker.alerts.engine import AlertMessage, Notifier, NotifierError, process_pending_events
from nettracker.alerts.notifiers import DiscordNotifier, build_notifiers
from nettracker.alerts.notifiers.discord import MAX_CONTENT_LENGTH
from nettracker.cli import main
from nettracker.config import AlertSettings, load_settings
from nettracker.db import Repository, connect, migrate
from nettracker.errors import ConfigError

WEBHOOK = "https://discord.com/api/webhooks/123456/secret-token-value"
BASE = 'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "discord-test.db"\n'


def make_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def message(text: str = "Nouvel appareil détecté : phone (aa:bb:cc:dd:ee:ff)") -> AlertMessage:
    return AlertMessage(event_id=1, kind="new_device", severity="critical", text=text)


def test_send_posts_one_json_message_without_mentions() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    notifier = DiscordNotifier(WEBHOOK, client=make_client(httpx.MockTransport(handler)))
    notifier.send(message())
    assert len(seen) == 1
    assert str(seen[0].url) == WEBHOOK
    body = json.loads(seen[0].content)
    assert "Nouvel appareil détecté" in body["content"]
    assert "[critical]" in body["content"]
    assert body["allowed_mentions"] == {"parse": []}


def test_long_text_is_truncated_to_the_discord_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    notifier = DiscordNotifier(WEBHOOK, client=make_client(httpx.MockTransport(handler)))
    notifier.send(message("x" * 5000))
    assert len(json.loads(seen[0].content)["content"]) == MAX_CONTENT_LENGTH


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500])
def test_http_errors_raise_without_leaking_the_url(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"error for {request.url}")

    notifier = DiscordNotifier(WEBHOOK, client=make_client(httpx.MockTransport(handler)))
    with pytest.raises(NotifierError) as excinfo:
        notifier.send(message())
    assert str(status) in str(excinfo.value)
    assert "secret-token-value" not in str(excinfo.value)


def test_transport_errors_raise_without_leaking_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    notifier = DiscordNotifier(WEBHOOK, client=make_client(httpx.MockTransport(handler)))
    with pytest.raises(NotifierError) as excinfo:
        notifier.send(message())
    assert "ConnectError" in str(excinfo.value)
    assert "secret-token-value" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_build_notifiers_is_empty_without_a_webhook() -> None:
    assert build_notifiers(AlertSettings()) == []


def test_build_notifiers_creates_discord_from_settings() -> None:
    settings = AlertSettings.model_validate({"discord": {"webhook_url": WEBHOOK}})
    notifiers = build_notifiers(settings)
    assert [notifier.name for notifier in notifiers] == ["discord"]


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/1/abc",
        "https://example.com/api/webhooks/1/abc",
        "https://discord.com.evil.example/api/webhooks/1/abc",
        "https://discord.com/other/1/abc",
        "not a url",
    ],
)
def test_webhook_url_must_be_a_discord_https_webhook(url: str) -> None:
    with pytest.raises(ValueError, match="Discord webhook"):
        AlertSettings.model_validate({"discord": {"webhook_url": url}})


def test_error_message_does_not_echo_the_url(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(BASE, encoding="utf-8")
    bad = "https://example.com/api/webhooks/1/very-secret-part"
    with pytest.raises(ConfigError) as excinfo:
        load_settings(config, environ={"NETTRACKER_DISCORD_WEBHOOK_URL": bad})
    assert "very-secret-part" not in str(excinfo.value)
    assert "alerts.discord.webhook_url" in str(excinfo.value)


def test_webhook_is_read_from_the_environment(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(BASE, encoding="utf-8")
    settings = load_settings(config, environ={"NETTRACKER_DISCORD_WEBHOOK_URL": WEBHOOK})
    assert settings.alerts.discord.webhook_url is not None
    assert settings.alerts.discord.webhook_url.get_secret_value() == WEBHOOK
    assert WEBHOOK not in repr(settings)


def test_empty_webhook_variable_means_not_configured(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(BASE, encoding="utf-8")
    settings = load_settings(config, environ={"NETTRACKER_DISCORD_WEBHOOK_URL": ""})
    assert settings.alerts.discord.webhook_url is None


class FailingNotifier:
    name = "discord"

    def send(self, message: AlertMessage) -> None:
        raise NotifierError("discord rejected the message (HTTP 500)")


def test_engine_records_sent_and_failed_per_notifier() -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    repo = Repository(conn)
    repo.add_event("collector_stale", created_at=datetime.now(UTC))
    sent: list[AlertMessage] = []

    class Recorder:
        name = "recorder"

        def send(self, message: AlertMessage) -> None:
            sent.append(message)

    notifiers: list[Notifier] = [Recorder(), FailingNotifier()]
    summary = process_pending_events(
        conn, AlertSettings(dry_run=False), datetime.now(UTC), notifiers
    )
    assert (summary.sent, summary.failed) == (1, 1)
    assert len(sent) == 1
    rows = conn.execute("SELECT channel, status, error FROM notifications ORDER BY id").fetchall()
    assert rows == [("recorder", "sent", None), ("discord", "failed", "NotifierError")]


def seed_event(directory: Path) -> None:
    conn = connect(directory / "discord-test.db")
    try:
        migrate(conn)
        Repository(conn).add_event("collector_stale", created_at=datetime.now(UTC))
    finally:
        conn.close()


@pytest.fixture
def cli_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in (
        "NETTRACKER_CONFIG",
        "NETTRACKER_API_TOKEN",
        "NETTRACKER_DATABASE_PATH",
        "NETTRACKER_DISCORD_WEBHOOK_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_cli_live_mode_sends_through_the_built_notifier(
    cli_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (cli_dir / "config.toml").write_text(BASE + "\n[alerts]\ndry_run = false\n", encoding="utf-8")
    monkeypatch.setenv("NETTRACKER_DISCORD_WEBHOOK_URL", WEBHOOK)
    seed_event(cli_dir)
    sent: list[AlertMessage] = []

    class Recorder:
        name = "discord"

        def send(self, message: AlertMessage) -> None:
            sent.append(message)

    monkeypatch.setattr("nettracker.cli.build_notifiers", lambda _settings: [Recorder()])
    assert main(["process-alerts"]) == 0
    assert "1 sent" in capsys.readouterr().out
    assert len(sent) == 1


def test_cli_dry_run_never_builds_notifiers(
    cli_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (cli_dir / "config.toml").write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("NETTRACKER_DISCORD_WEBHOOK_URL", WEBHOOK)
    seed_event(cli_dir)

    def boom(_settings: AlertSettings) -> list[Notifier]:
        raise AssertionError("notifiers must not be built in dry-run")

    monkeypatch.setattr("nettracker.cli.build_notifiers", boom)
    assert main(["process-alerts"]) == 0
    assert "1 dry-run" in capsys.readouterr().out


def test_check_config_reports_the_webhook_without_printing_it(
    cli_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (cli_dir / "config.toml").write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("NETTRACKER_DISCORD_WEBHOOK_URL", WEBHOOK)
    assert main(["check-config"]) == 0
    output = capsys.readouterr().out
    assert "alerts.discord: webhook set" in output
    assert "secret-token-value" not in output
