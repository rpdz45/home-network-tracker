"""Opt-in Bbox API diagnostics; GET only, no credentials or router changes."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from urllib.parse import urlsplit

import httpx

from nettracker.errors import NetTrackerError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PRIVATE_NETWORKS = tuple(
    IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
READ_PATHS = {
    "/api/v1/device": ("device",),
    "/api/v1/parentalcontrol": ("parentalcontrol",),
    "/api/v1/parentalcontrol/scheduler": ("parentalcontrol", "scheduler"),
}


class BboxError(NetTrackerError):
    """A sanitized diagnostic validation, transport or response error."""


class ProbeState(StrEnum):
    ACCESSIBLE = "accessible"
    AUTH_REQUIRED = "authentication_or_permission_required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EndpointProbe:
    path: str
    state: ProbeState


def _origin(base_url: str, networks: Sequence[IPv4Network], allow_http: bool) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in base_url):
        raise BboxError("invalid Bbox address")
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
            raise BboxError("invalid Bbox address")
        address = IPv4Address(url.hostname or "")
        if url.port not in {None, 80 if url.scheme == "http" else 443}:
            raise BboxError("unsupported Bbox port")
    except ValueError:
        raise BboxError("invalid Bbox address") from None
    if not any(address in network for network in PRIVATE_NETWORKS) or not any(
        address in network for network in networks
    ):
        raise BboxError("Bbox address is outside allowed private subnets")
    if url.scheme == "http" and allow_http is not True:
        raise BboxError("unencrypted local HTTP requires explicit authorization")
    return f"{url.scheme}://{address}"


def _probe(client: httpx.Client, origin: str, path: str) -> EndpointProbe:
    if path not in READ_PATHS:
        raise BboxError("Bbox diagnostic operation is not allowed")
    try:
        with client.stream("GET", origin + path) as response:
            if response.status_code in {401, 403}:
                return EndpointProbe(path, ProbeState.AUTH_REQUIRED)
            if response.status_code == 404:
                return EndpointProbe(path, ProbeState.UNAVAILABLE)
            if response.status_code != 200:
                raise BboxError(f"Bbox diagnostic returned HTTP {response.status_code}")
            if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
                raise BboxError("compressed Bbox responses are not supported")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise BboxError("Bbox diagnostic response exceeds size limit")
                data.extend(chunk)
        reply = json.loads(data)
    except (httpx.HTTPError, ValueError, RecursionError):
        raise BboxError("Bbox diagnostic request or JSON response failed") from None
    if isinstance(reply, list) and len(reply) == 1:
        reply = reply[0]
    for key in READ_PATHS[path]:
        if not isinstance(reply, dict) or not isinstance(reply.get(key), dict):
            raise BboxError("unrecognized Bbox diagnostic response")
        reply = reply[key]
    return EndpointProbe(path, ProbeState.ACCESSIBLE)


def read_diagnostic(
    base_url: str,
    allowed_subnets: Sequence[IPv4Network],
    *,
    enabled: bool = False,
    allow_http: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> tuple[EndpointProbe, ...]:
    """Probe fixed endpoints; stop at the first access refusal or missing endpoint.

    Returned states describe endpoint access, not model compatibility or blocking.
    No response bodies, credentials or device inventories are retained.
    """
    if enabled is not True:
        raise BboxError("Bbox diagnostics require explicit activation")
    origin = _origin(base_url, allowed_subnets, allow_http)
    with httpx.Client(
        transport=transport,
        timeout=5.0,
        follow_redirects=False,
        trust_env=False,
        verify=True,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-Requested-With": "XmlHttpRequest",
            "Origin": origin,
            "Referer": origin + "/login",
        },
    ) as client:
        results: list[EndpointProbe] = []
        for path in READ_PATHS:
            result = _probe(client, origin, path)
            results.append(result)
            if result.state != ProbeState.ACCESSIBLE:
                break
        return tuple(results)
