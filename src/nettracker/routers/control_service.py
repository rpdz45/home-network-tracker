"""Compose local inventory, confirmation guards and the Livebox adapter."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import httpx
from pydantic import SecretStr

from nettracker.db.control_inventory import resolve_control_target
from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.routers.livebox5_control import ControlResult, change_schedule


@dataclass(frozen=True)
class LiveboxControlConfig:
    database: Path
    base_url: str
    networks: tuple[IPv4Network, ...]
    password: SecretStr = field(repr=False)
    expected_firmware: str
    management_mac: str
    gateway_mac: str
    enabled: bool = False
    allow_http: bool = False
    max_age: timedelta = timedelta(seconds=60)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_livebox_control(
    config: LiveboxControlConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> ControlGuards[ControlResult]:
    """Build once per single-process application; do not build per web request.

    Construction performs no database or network I/O. Credentials and settings
    must originate from trusted server configuration, never browser fields.
    """
    if not timedelta(0) < config.max_age <= timedelta(minutes=5):
        raise ValueError("freshness must be positive and at most five minutes")
    protected = tuple(
        AccessRequest(RouterKind.LIVEBOX5, IPv4Address("192.168.0.1"), mac, False).mac
        for mac in (config.management_mac, config.gateway_mac)
    )

    def resolve(device_id: int, blocked: bool) -> AccessRequest:
        conn: sqlite3.Connection | None = None
        try:
            uri = config.database.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
            return resolve_control_target(
                conn,
                device_id,
                blocked,
                router=RouterKind.LIVEBOX5,
                now=now(),
                max_age=config.max_age,
            )
        except sqlite3.Error:
            raise AccessControlError("local inventory is unavailable; no change permitted") from None
        finally:
            if conn is not None:
                conn.close()

    def execute(request: AccessRequest) -> ControlResult:
        return change_schedule(
            config.base_url,
            config.networks,
            config.password,
            request,
            expected_firmware=config.expected_firmware,
            management_mac=protected[0],
            gateway_mac=protected[1],
            enabled=config.enabled,
            confirmed=True,
            allow_http=config.allow_http,
            transport=transport,
        )

    return ControlGuards(
        resolve,
        execute,
        config.networks,
        protected,
        enabled=config.enabled,
    )
