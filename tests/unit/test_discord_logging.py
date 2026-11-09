"""Credential-bearing Discord requests must never appear in HTTP client logs."""

import io
import logging
import secrets

import httpx
import pytest

from nettracker.alerts.engine import AlertMessage, NotifierError
from nettracker.alerts.notifiers import DiscordNotifier


def _message() -> AlertMessage:
    return AlertMessage(1, "collector_stale", "critical", "Collecteur indisponible")


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
@pytest.mark.parametrize("status", [204, 302, 400, 429, 500])
def test_discord_request_logs_never_contain_the_webhook(
    caplog: pytest.LogCaptureFixture, level: int, status: int
) -> None:
    token = secrets.token_urlsafe(32)
    webhook = f"https://discord.com/api/webhooks/123456/{token}"
    caplog.set_level(level)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status))
    ) as client:
        notifier = DiscordNotifier(webhook, client=client)
        if status == 204:
            notifier.send(_message())
        else:
            with pytest.raises(NotifierError):
                notifier.send(_message())
    assert webhook not in caplog.text
    assert token not in caplog.text
    assert "HTTP Request" in caplog.text


def test_webhook_protection_does_not_disable_other_http_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    token = secrets.token_urlsafe(32)
    webhook = f"https://discord.com/api/webhooks/123456/{token}"
    ordinary = "https://example.com/health"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(204))
    ) as client:
        DiscordNotifier(webhook, client=client).send(_message())
        client.get(ordinary)
    assert ordinary in caplog.text
    assert token not in caplog.text


def test_repeated_notifiers_do_not_accumulate_log_filters() -> None:
    logger = logging.getLogger("httpx")
    token = secrets.token_urlsafe(32)
    webhook = f"https://discord.com/api/webhooks/123456/{token}"
    DiscordNotifier(webhook)
    count = len(logger.filters)
    DiscordNotifier(webhook)
    assert len(logger.filters) == count


@pytest.mark.parametrize(
    "logger_name",
    [
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    ],
)
def test_low_level_request_target_is_redacted(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    caplog.set_level(logging.DEBUG)
    token = secrets.token_urlsafe(32)
    path = f"/api/webhooks/123456/{token}"
    DiscordNotifier(f"https://discord.com{path}")
    logging.getLogger(logger_name).debug("request target=%r", path.encode())
    assert token not in caplog.text
    assert "[redacted]" in caplog.text


def test_all_handlers_receive_redacted_request_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("httpx")
    logger.addHandler(handler)
    token = secrets.token_urlsafe(32)
    webhook = f"https://discord.com/api/webhooks/123456/{token}"
    try:
        with httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(204))
        ) as client:
            DiscordNotifier(webhook, client=client).send(_message())
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert token not in output.getvalue()
    assert "[redacted]" in output.getvalue()
    assert token not in caplog.text
