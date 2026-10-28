"""Opt-in, read-only Livebox 5 snapshot client; no router configuration methods."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from nettracker.errors import NetTrackerError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DEVICES = 512
PRIVATE_NETWORKS = tuple(
    IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
ALLOWED_CALLS = frozenset(
    {
        ("sysbus.DeviceInfo", "get"),
        ("sah.Device.Information", "createContext"),
        ("sysbus.Devices", "get"),
    }
)


class LiveboxError(NetTrackerError):
    """A sanitized validation, transport, authentication or response error."""


@dataclass(frozen=True)
class LiveboxSnapshot:
    model: str
    firmware: str | None
    devices: tuple[dict[str, Any], ...]


def _endpoint(base_url: str, networks: Sequence[IPv4Network], allow_http: bool) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in base_url):
        raise LiveboxError("invalid Livebox address")
    try:
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise LiveboxError("invalid Livebox address")
        address = IPv4Address(url.hostname or "")
        expected_port = 80 if url.scheme == "http" else 443
        if url.port not in {None, expected_port}:
            raise LiveboxError("unsupported Livebox port")
    except ValueError:
        raise LiveboxError("invalid Livebox address") from None
    if not any(address in private for private in PRIVATE_NETWORKS) or not any(
        address in network for network in networks
    ):
        raise LiveboxError("Livebox address is outside allowed private subnets")
    if url.scheme == "http" and allow_http is not True:
        raise LiveboxError("unencrypted local HTTP requires explicit authorization")
    return f"{url.scheme}://{address}/ws"


def _post(
    client: httpx.Client,
    endpoint: str,
    service: str,
    method: str,
    parameters: dict[str, object],
    *,
    context: str | None = None,
    login: bool = False,
) -> dict[str, Any]:
    if (service, method) not in ALLOWED_CALLS:
        raise LiveboxError("router operation is not allowed by this read-only client")
    headers = {"Content-Type": "application/x-sah-ws-4-call+json; charset=UTF-8"}
    if login:
        headers["Authorization"] = "X-Sah-Login"
    elif context is not None:
        headers["Authorization"] = f"X-Sah {context}"
        headers["X-Context"] = context
    try:
        with client.stream(
            "POST",
            endpoint,
            headers=headers,
            json={"service": service, "method": method, "parameters": parameters},
            timeout=5.0,
        ) as response:
            if response.status_code != 200:
                raise LiveboxError(f"Livebox returned HTTP {response.status_code}")
            if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
                raise LiveboxError("compressed Livebox responses are not supported")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise LiveboxError("Livebox response exceeds size limit")
                data.extend(chunk)
        reply = json.loads(data)
    except (httpx.HTTPError, ValueError, RecursionError):
        raise LiveboxError("Livebox request or JSON response failed") from None
    if isinstance(reply, dict) and "result" in reply:
        reply = reply["result"]
    if not isinstance(reply, dict):
        raise LiveboxError("unexpected Livebox response structure")
    if "error" in reply or reply.get("errors") or reply.get("status") is False:
        raise LiveboxError("Livebox refused the request")
    return cast(dict[str, Any], reply)


def read_snapshot(
    base_url: str,
    allowed_subnets: Sequence[IPv4Network],
    password: SecretStr,
    *,
    enabled: bool = False,
    allow_http: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> LiveboxSnapshot:
    """Identify before sending credentials; retain neither credentials nor cookies on disk."""
    if enabled is not True:
        raise LiveboxError("Livebox access requires explicit activation")
    endpoint = _endpoint(base_url, allowed_subnets, allow_http)
    if not isinstance(password, SecretStr) or not password.get_secret_value():
        raise LiveboxError("a local Livebox administrator password is required")
    with httpx.Client(
        transport=transport,
        timeout=5.0,
        follow_redirects=False,
        trust_env=False,
        verify=True,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    ) as client:
        identity = _post(client, endpoint, "sysbus.DeviceInfo", "get", {}).get("status")
        if not isinstance(identity, dict) or identity.get("ProductClass") not in {
            "Livebox Fibre",
            "Livebox 5",
        }:
            raise LiveboxError("router is not a recognized Livebox 5")
        firmware = identity.get("SoftwareVersion")
        if not isinstance(firmware, str) or len(firmware) > 256:
            firmware = None
        authentication = _post(
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
        context = authentication.get("contextID") if isinstance(authentication, dict) else None
        if not isinstance(context, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,256}", context) is None:
            raise LiveboxError("Livebox authentication did not return a valid context")
        devices = _post(
            client,
            endpoint,
            "sysbus.Devices",
            "get",
            {"expression": "physical and !self and !voice"},
            context=context,
        ).get("status")
        if (
            not isinstance(devices, list)
            or len(devices) > MAX_DEVICES
            or not all(isinstance(device, dict) for device in devices)
        ):
            raise LiveboxError("unexpected Livebox device list")
        return LiveboxSnapshot("Livebox 5", firmware, tuple(dict(device) for device in devices))
