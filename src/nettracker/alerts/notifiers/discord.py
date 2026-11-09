"""Discord webhook notifier.

The webhook URL is a secret: it is never logged and never put in an exception message.
Failures raise ``NotifierError`` with a fixed text (plus the HTTP status code when there is one).
"""

import logging

import httpx

from nettracker.alerts.engine import AlertMessage, Notifier, NotifierError
from nettracker.config import AlertSettings

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 2000
_SEVERITY_PREFIX = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


class DiscordNotifier:
    """Send each alert as one message to a Discord webhook."""

    name = "discord"

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds
        self._client = client

    def send(self, message: AlertMessage) -> None:
        prefix = _SEVERITY_PREFIX.get(message.severity, "")
        content = f"{prefix} [{message.severity}] {message.text}".strip()
        payload = {
            "content": content[:MAX_CONTENT_LENGTH],
            # Never let a device name trigger @everyone or role mentions.
            "allowed_mentions": {"parse": []},
        }
        try:
            if self._client is not None:
                response = self._client.post(self._webhook_url, json=payload)
            else:
                with httpx.Client(timeout=self._timeout, follow_redirects=False) as client:
                    response = client.post(self._webhook_url, json=payload)
        except httpx.HTTPError as exc:
            # The exception text can contain the webhook URL: keep only its type.
            raise NotifierError(f"discord delivery failed ({type(exc).__name__})") from None
        if not response.is_success:
            raise NotifierError(f"discord rejected the message (HTTP {response.status_code})")


def build_notifiers(settings: AlertSettings) -> list[Notifier]:
    """Build the notifiers that are configured. An empty list means none."""
    notifiers: list[Notifier] = []
    webhook = settings.discord.webhook_url
    if webhook is not None and webhook.get_secret_value():
        notifiers.append(
            DiscordNotifier(
                webhook.get_secret_value(), timeout_seconds=settings.discord.timeout_seconds
            )
        )
    return notifiers
