"""Opt-in, read-only Fing Local API inventory and exact MAC/IP matching."""

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPException
from ipaddress import IPv4Address, IPv4Network, ip_address
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from nettracker.db.repository import normalize_mac
from nettracker.discovery.scope import ScopeError, require_allowed_target
from nettracker.errors import NetTrackerError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DEVICES = 1024


class FingError(NetTrackerError):
    """Sanitized Fing configuration, transport or inventory error."""


class _RawDevice(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    mac: str = Field(max_length=32)
    ip: list[str] = Field(max_length=16)
    state: Literal["UP", "DOWN"]
    name: str | None = Field(default=None, max_length=512)
    make: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=512)
    kind: str | None = Field(default=None, alias="type", max_length=512)


class _RawInventory(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    network_id: str = Field(alias="networkId", min_length=1, max_length=128)
    devices: list[_RawDevice] = Field(max_length=MAX_DEVICES)


@dataclass(frozen=True)
class FingDevice:
    mac: str
    addresses: tuple[str, ...]
    name: str | None
    manufacturer: str | None
    model: str | None
    device_type: str | None
    reported_state: Literal["UP", "DOWN"]


@dataclass(frozen=True)
class FingInventory:
    network_id: str
    retrieved_at: datetime
    devices: tuple[FingDevice, ...]
    excluded_devices: int
    source: Literal["fing_local_api"] = "fing_local_api"


def _text(value: str | None, secret: str) -> str | None:
    if value is None:
        return None
    text = " ".join(value.replace(secret, "[redacted]").split())[:128]
    return text or None


def _read_local(secret: str) -> bytes:
    """Use a fixed loopback target; no HTTPX URL logging, redirects or proxies."""
    try:
        with closing(HTTPConnection("127.0.0.1", 49090, timeout=5.0)) as connection:
            connection.set_debuglevel(0)
            connection.request(
                "GET",
                "/1/devices?" + urlencode({"auth": secret}),
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise FingError(f"Fing inventory returned HTTP {response.status}")
            encoding = response.getheader("Content-Encoding") or ""
            if encoding.strip().lower() not in {"", "identity"}:
                raise FingError("compressed Fing responses are not supported")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise FingError("Fing inventory response exceeds size limit")
            return body
    except (OSError, HTTPException, ValueError):
        raise FingError("Fing local inventory request failed") from None


def _mac(value: str) -> str:
    try:
        mac = normalize_mac(value)
    except ValueError:
        raise FingError("invalid Fing MAC address") from None
    octets = bytes.fromhex(mac.replace(":", ""))
    if not any(octets) or octets[0] & 1:
        raise FingError("non-unicast or zero Fing MAC address")
    return mac


def _addresses(values: list[str], networks: list[IPv4Network]) -> tuple[str, ...]:
    addresses: set[str] = set()
    for value in values:
        try:
            address = ip_address(value)
        except ValueError:
            raise FingError("invalid Fing IP address") from None
        if isinstance(address, IPv4Address) and any(address in network for network in networks):
            addresses.add(str(address))
    return tuple(sorted(addresses))


def read_inventory(
    api_key: SecretStr,
    allowed_subnets: list[IPv4Network],
    *,
    enabled: bool = False,
    confirmed: bool = False,
) -> FingInventory:
    """Read already-discovered devices; never trigger scans or modify access rules.

    Returned identities are Fing reports, not independently verified device models.
    retrieved_at is the API retrieval time, not a discovery or presence timestamp.
    """
    if enabled is not True or confirmed is not True:
        raise FingError("Fing inventory requires activation and confirmation")
    if not isinstance(api_key, SecretStr) or not 1 <= len(api_key.get_secret_value()) <= 4096:
        raise FingError("a non-empty local Fing API key is required")
    if not allowed_subnets:
        raise FingError("Fing inventory requires allowed private subnets")
    try:
        for network in allowed_subnets:
            require_allowed_target(str(network), allowed_subnets)
    except ScopeError:
        raise FingError("invalid Fing private subnet configuration") from None
    secret = api_key.get_secret_value()
    body = _read_local(secret)
    try:
        raw = _RawInventory.model_validate_json(body)
    except ValidationError:
        raise FingError("unexpected Fing inventory structure") from None
    devices: list[FingDevice] = []
    macs: set[str] = set()
    addresses_seen: set[str] = set()
    excluded = 0
    for entry in raw.devices:
        mac = _mac(entry.mac)
        addresses = _addresses(entry.ip, allowed_subnets)
        if not addresses:
            excluded += 1
            continue
        if mac in macs or addresses_seen.intersection(addresses):
            raise FingError("ambiguous Fing MAC or IP associations")
        macs.add(mac)
        addresses_seen.update(addresses)
        devices.append(
            FingDevice(
                mac,
                addresses,
                _text(entry.name, secret),
                _text(entry.make, secret),
                _text(entry.model, secret),
                _text(entry.kind, secret),
                entry.state,
            )
        )
    return FingInventory(
        _text(raw.network_id, secret) or "", datetime.now(UTC), tuple(devices), excluded
    )


def match_identity(inventory: FingInventory, mac: str, ip: str) -> FingDevice | None:
    """Require exact MAC and IPv4 agreement; never merge on name or IP alone."""
    normalized = _mac(mac)
    try:
        address = str(IPv4Address(ip))
    except ValueError:
        raise FingError("matching requires a literal IPv4 address") from None
    matches = [
        device
        for device in inventory.devices
        if device.mac == normalized and address in device.addresses
    ]
    if len(matches) > 1:
        raise FingError("ambiguous Fing identity match")
    return matches[0] if matches else None
