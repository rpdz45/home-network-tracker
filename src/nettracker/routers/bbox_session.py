"""Opt-in Bbox administrator login and host inventory; no access-rule writes."""

import json
import math
import re
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr

from nettracker.routers.bbox import BboxError, _origin

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_HOSTS = 512
ALLOWED_CALLS = frozenset(
    {
        ("PUT", "/api/v1/login"),
        ("GET", "/api/v1/device"),
        ("GET", "/api/v1/hosts"),
        ("POST", "/api/v1/logout"),
    }
)


@dataclass(frozen=True)
class BboxHost:
    identifier: int
    name: str | None
    address: str | None
    mac: str
    active: bool | None
    blocked: bool | None


@dataclass(frozen=True)
class BboxSnapshot:
    model: str
    firmware: str | None
    hosts: tuple[BboxHost, ...]
    session_closed: bool


def _text(value: object, sensitive: tuple[str, ...]) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    text = value
    for secret in sensitive:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:128]


def _flag(value: object) -> bool | None:
    if type(value) is bool:
        return cast(bool, value)
    if type(value) is int and value in {0, 1}:
        return bool(value)
    return None


def _request(
    client: httpx.Client,
    origin: str,
    method: str,
    path: str,
    *,
    form: dict[str, str] | None = None,
) -> object:
    if (method, path) not in ALLOWED_CALLS:
        raise BboxError("Bbox authenticated operation is not allowed")
    try:
        with client.stream(method, origin + path, data=form) as response:
            expected = {200, 204} if path == "/api/v1/logout" else {200}
            if response.status_code not in expected:
                raise BboxError(f"Bbox authenticated request returned HTTP {response.status_code}")
            if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
                raise BboxError("compressed Bbox responses are not supported")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise BboxError("Bbox authenticated response exceeds size limit")
                data.extend(chunk)
        return json.loads(data) if method == "GET" else None
    except (httpx.HTTPError, ValueError, RecursionError):
        raise BboxError("Bbox authenticated request or JSON response failed") from None


def _unwrap(reply: object, key: str) -> dict[str, Any]:
    if isinstance(reply, list) and len(reply) == 1:
        reply = reply[0]
    if not isinstance(reply, dict) or "error" in reply or not isinstance(reply.get(key), dict):
        raise BboxError("unexpected Bbox authenticated response structure")
    return cast(dict[str, Any], reply[key])


def _hosts(reply: object, sensitive: tuple[str, ...]) -> tuple[BboxHost, ...]:
    entries = _unwrap(reply, "hosts").get("list")
    if not isinstance(entries, list) or len(entries) > MAX_HOSTS:
        raise BboxError("unexpected Bbox host list")
    hosts: list[BboxHost] = []
    identifiers: set[int] = set()
    macs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BboxError("unexpected Bbox host entry")
        identifier = entry.get("id")
        mac = entry.get("macaddress")
        if type(identifier) is not int or identifier < 0 or identifier in identifiers:
            raise BboxError("invalid or duplicate Bbox host identifier")
        if (
            not isinstance(mac, str)
            or re.fullmatch(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", mac) is None
        ):
            raise BboxError("invalid Bbox host MAC address")
        mac = mac.upper()
        octets = bytes.fromhex(mac.replace(":", ""))
        if mac in macs or octets[0] & 1 or not any(octets):
            raise BboxError("duplicate or non-unicast Bbox host MAC address")
        identifiers.add(identifier)
        macs.add(mac)
        hosts.append(
            BboxHost(
                identifier,
                _text(entry.get("hostname"), sensitive),
                _text(entry.get("ipaddress"), sensitive),
                _text(mac, sensitive) or "",
                _flag(entry.get("active")),
                _flag(entry.get("blocked")),
            )
        )
    return tuple(hosts)


def read_authenticated_snapshot(
    base_url: str,
    allowed_subnets: Sequence[IPv4Network],
    password: SecretStr,
    expected_model: str,
    *,
    enabled: bool = False,
    confirmed: bool = False,
    allow_http: bool = False,
    timeout_seconds: float = 5.0,
    ca_file: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> BboxSnapshot:
    """Login once, read the expected model and hosts, then attempt session logout.

    Model checking happens after login: this is not pre-authentication identification.
    The caller must trust the configured endpoint before supplying credentials.
    """
    if enabled is not True or confirmed is not True:
        raise BboxError("Bbox administrator access requires activation and confirmation")
    origin = _origin(base_url, allowed_subnets, allow_http)
    if not isinstance(password, SecretStr) or not password.get_secret_value():
        raise BboxError("a local Bbox administrator password is required")
    if not isinstance(expected_model, str) or not 1 <= len(expected_model) <= 128:
        raise BboxError("an exact expected Bbox model is required")
    if not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 30:
        raise BboxError("Bbox timeout must be between 0.1 and 30 seconds")
    try:
        verification: bool | ssl.SSLContext = (
            ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else True
        )
    except (OSError, ValueError):
        raise BboxError("Bbox certificate trust configuration failed") from None
    with httpx.Client(
        transport=transport,
        timeout=timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        verify=verification,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-Requested-With": "XmlHttpRequest",
            "Origin": origin,
            "Referer": origin + "/login",
        },
    ) as client:
        secret = password.get_secret_value()
        authenticated = False
        closed = False
        try:
            _request(
                client, origin, "PUT", "/api/v1/login", form={"password": secret, "remember": "1"}
            )
            cookie_header = client.build_request("GET", origin + "/api/v1/device").headers.get(
                "cookie", ""
            )
            cookies: SimpleCookie[str] = SimpleCookie()
            try:
                cookies.load(cookie_header)
            except CookieError:
                raise BboxError("Bbox login returned an invalid session cookie") from None
            session = cookies.get("BBOX_ID")
            if session is None or not session.value:
                raise BboxError("Bbox login did not return a usable session cookie")
            authenticated = True
            device = _unwrap(_request(client, origin, "GET", "/api/v1/device"), "device")
            if device.get("modelname") != expected_model:
                raise BboxError("Bbox model does not match the configured expectation")
            main = device.get("main")
            firmware = main.get("version") if isinstance(main, dict) else None
            if not isinstance(firmware, str) or not firmware:
                firmware = device.get("firmware")
            sensitive = (secret, session.value)
            hosts = _hosts(_request(client, origin, "GET", "/api/v1/hosts"), sensitive)
        finally:
            if authenticated:
                try:
                    _request(client, origin, "POST", "/api/v1/logout")
                    closed = True
                except BboxError:
                    closed = False
        return BboxSnapshot(
            _text(expected_model, sensitive) or "", _text(firmware, sensitive), hosts, closed
        )
