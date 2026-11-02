"""Explicit single-target schedule control; never called by dashboard GETs."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from nettracker.routers.control import (
    PRIVATE_NETWORKS,
    AccessControlError,
    AccessRequest,
    RouterKind,
)
from nettracker.routers.livebox5 import LiveboxError, _endpoint, _post
from nettracker.routers.livebox5_access import ScheduleState, override_parameters, parse_schedule

MAX_REPLY_BYTES = 256 * 1024


@dataclass(frozen=True)
class ControlResult:
    changed: bool
    state: ScheduleState


def _scheduler(
    client: httpx.Client,
    endpoint: str,
    context: str,
    method: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    if method not in {"getSchedule", "overrideSchedule"}:
        raise AccessControlError("scheduler operation is not allowed")
    try:
        with client.stream(
            "POST",
            endpoint,
            headers={
                "Content-Type": "application/x-sah-ws-4-call+json; charset=UTF-8",
                "Authorization": f"X-Sah {context}",
                "X-Context": context,
            },
            json={"service": "sysbus.Scheduler", "method": method, "parameters": parameters},
            timeout=5.0,
        ) as response:
            if response.status_code != 200:
                raise AccessControlError("scheduler HTTP request refused")
            if response.headers.get("content-encoding", "").lower().strip() not in {"", "identity"}:
                raise AccessControlError("compressed scheduler response refused")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_REPLY_BYTES:
                    raise AccessControlError("scheduler response exceeds size limit")
                data.extend(chunk)
        reply = json.loads(data)
    except (httpx.HTTPError, ValueError, RecursionError):
        raise AccessControlError("scheduler transport or JSON failed") from None
    if isinstance(reply, dict) and "result" in reply:
        reply = reply["result"]
    if (
        not isinstance(reply, dict)
        or "error" in reply
        or reply.get("errors")
        or reply.get("status") is not True
    ):
        raise AccessControlError("scheduler response is not confirmed")
    return cast(dict[str, object], reply)


def change_schedule(
    base_url: str,
    networks: Sequence[IPv4Network],
    password: SecretStr,
    request: AccessRequest,
    *,
    expected_firmware: str,
    management_mac: str,
    gateway_mac: str,
    enabled: bool = False,
    confirmed: bool = False,
    allow_http: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> ControlResult:
    """Restore schedules on release; a release need not grant immediate access."""
    if enabled is not True or confirmed is not True:
        raise AccessControlError("activation and target confirmation are required")
    if request.router != RouterKind.LIVEBOX5:
        raise AccessControlError("a Livebox 5 target is required")
    if not any(request.address in n for n in PRIVATE_NETWORKS) or not any(
        request.address in n for n in networks
    ):
        raise AccessControlError("target is outside allowed private subnets")
    protected = frozenset(
        AccessRequest(RouterKind.LIVEBOX5, request.address, mac, False).mac
        for mac in (management_mac, gateway_mac)
    )
    if request.mac in protected:
        raise AccessControlError("management device and gateway are protected")
    if not expected_firmware or len(expected_firmware) > 256:
        raise AccessControlError("an exact expected firmware is required")
    endpoint = _endpoint(base_url, networks, allow_http)
    if str(request.address) == urlsplit(endpoint).hostname:
        raise AccessControlError("router address cannot be targeted")
    if not isinstance(password, SecretStr) or not password.get_secret_value():
        raise AccessControlError("administrator credentials are required")
    with httpx.Client(
        transport=transport,
        timeout=5.0,
        follow_redirects=False,
        trust_env=False,
        verify=True,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    ) as client:
        identity = _post(client, endpoint, "sysbus.DeviceInfo", "get", {}).get("status")
        if (
            not isinstance(identity, dict)
            or identity.get("ProductClass") not in {"Livebox 5", "Livebox Fibre"}
            or identity.get("SoftwareVersion") != expected_firmware
        ):
            raise AccessControlError("router model or firmware does not match")
        auth = _post(
            client,
            endpoint,
            "sah.Device.Information",
            "createContext",
            {
                "applicationName": "so_sdkut",
                "username": "admin",
                "password": password.get_secret_value(),
            },
            login=True,
        ).get("data")
        context = auth.get("contextID") if isinstance(auth, dict) else None
        if not isinstance(context, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,256}", context) is None:
            raise AccessControlError("invalid authenticated context")
        target: dict[str, object] = {"type": "ToD", "ID": request.mac}
        before = parse_schedule(_scheduler(client, endpoint, context, "getSchedule", target))
        desired = "Disable" if request.blocked else ""
        if before.override == desired and (not request.blocked or before.blocked):
            return ControlResult(False, before)
        parameters = override_parameters(
            request.mac, before, blocked=request.blocked, protected_macs=protected, confirmed=True
        )
        try:
            _scheduler(client, endpoint, context, "overrideSchedule", parameters)
            after = parse_schedule(_scheduler(client, endpoint, context, "getSchedule", target))
            if after.override != desired or (request.blocked and not after.blocked):
                raise AccessControlError("read-back mismatch")
        except (AccessControlError, LiveboxError):
            raise AccessControlError(
                "change outcome is uncertain; do not retry automatically"
            ) from None
        return ControlResult(True, after)
