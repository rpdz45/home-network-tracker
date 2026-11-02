"""Compose Bbox interlocks with an injected session; no HTTP adapter here."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from nettracker.db.control_inventory import resolve_control_target
from nettracker.routers.bbox_control import BboxControlPort, change_bbox_access
from nettracker.routers.control import AccessControlError, AccessRequest, AccessResult, RouterKind
from nettracker.routers.control_guards import ControlGuards


@dataclass(frozen=True)
class BboxControlConfig:
    database: Path
    networks: tuple[IPv4Network, ...]
    expected_model: str
    expected_firmware: str
    gateway_address: IPv4Address
    management_mac: str
    gateway_mac: str
    enabled: bool = False
    max_age: timedelta = timedelta(seconds=60)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_bbox_control(
    config: BboxControlConfig,
    session_factory: Callable[[], AbstractContextManager[BboxControlPort]],
    *,
    now: Callable[[], datetime] = _utc_now,
) -> ControlGuards[AccessResult]:
    """Build one shared instance; session factory is trusted server code."""
    if not config.expected_model or not config.expected_firmware:
        raise ValueError("exact Bbox model and firmware are required")
    if not timedelta(0) < config.max_age <= timedelta(minutes=5):
        raise ValueError("freshness must be positive and at most five minutes")
    if not isinstance(config.gateway_address, IPv4Address):
        raise ValueError("an IPv4 gateway is required")
    protected = tuple(
        AccessRequest(RouterKind.BBOX, config.gateway_address, mac, False).mac
        for mac in (config.management_mac, config.gateway_mac)
    )

    def resolve(device_id: int, blocked: bool) -> AccessRequest:
        conn: sqlite3.Connection | None = None
        try:
            uri = config.database.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
            request = resolve_control_target(
                conn,
                device_id,
                blocked,
                router=RouterKind.BBOX,
                now=now(),
                max_age=config.max_age,
            )
        except sqlite3.Error:
            raise AccessControlError(
                "local inventory is unavailable; no change permitted"
            ) from None
        finally:
            if conn is not None:
                conn.close()
        if request.address == config.gateway_address:
            raise AccessControlError("gateway address is protected")
        return request

    def execute(request: AccessRequest) -> AccessResult:
        result: AccessResult | None = None
        try:
            with session_factory() as port:
                result = change_bbox_access(
                    request,
                    port,
                    config.networks,
                    expected_model=config.expected_model,
                    expected_firmware=config.expected_firmware,
                    gateway_address=config.gateway_address,
                    management_mac=protected[0],
                    gateway_mac=protected[1],
                    enabled=config.enabled,
                    confirmed=True,
                )
        except AccessControlError:
            raise
        except Exception:
            raise AccessControlError(
                "Bbox session failed; outcome may be uncertain; do not retry automatically"
            ) from None
        if result is None:
            raise AccessControlError("Bbox session suppressed an error; outcome is uncertain")
        return result

    return ControlGuards(
        resolve, execute, config.networks, protected, enabled=config.enabled
    )
