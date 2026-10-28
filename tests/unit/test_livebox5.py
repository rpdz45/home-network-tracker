"""Synthetic Livebox replies and MockTransport only; no router access."""

import json
from ipaddress import IPv4Network

import httpx
import pytest
from pydantic import SecretStr

from nettracker.routers import livebox5

NETWORKS = [IPv4Network("192.168.1.0/24")]
PASSWORD = SecretStr("fixture-not-a-real-password")


def forbidden(request: httpx.Request) -> httpx.Response:
    pytest.fail("unexpected HTTP request")


@pytest.mark.parametrize(
    "address",
    [
        "https://example.com",
        "https://127.0.0.1",
        "https://8.8.8.8",
        "https://10.0.0.1",
        "https://192.168.1.1/other",
        "https://user:secret@192.168.1.1",
        "https://192.168.1.1?x=y",
        "https://192.168.1.1#fragment",
        "ftp://192.168.1.1",
        "https://192.168.1.1:8443",
        "https://192.168.1.1:bad",
        "https://[::1]",
        "https://192.168.1.1\n",
    ],
)
def test_invalid_targets_send_nothing(address: str) -> None:
    with pytest.raises(livebox5.LiveboxError):
        livebox5.read_snapshot(
            address, NETWORKS, PASSWORD, enabled=True, transport=httpx.MockTransport(forbidden)
        )


def test_disabled_access_sends_nothing() -> None:
    with pytest.raises(livebox5.LiveboxError, match="activation"):
        livebox5.read_snapshot(
            "https://192.168.1.1", NETWORKS, PASSWORD, transport=httpx.MockTransport(forbidden)
        )


def test_http_requires_separate_acknowledgment() -> None:
    with pytest.raises(livebox5.LiveboxError, match="HTTP"):
        livebox5.read_snapshot(
            "http://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(forbidden),
        )


def test_empty_password_sends_nothing() -> None:
    with pytest.raises(livebox5.LiveboxError, match="password"):
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            SecretStr(""),
            enabled=True,
            transport=httpx.MockTransport(forbidden),
        )


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize(
    ("base_url", "allow_http"),
    [("https://192.168.1.1", False), ("http://192.168.1.1", True)],
)
def test_identification_precedes_authentication_and_read(
    wrapped: bool, base_url: str, allow_http: bool
) -> None:
    calls: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert str(request.url) == f"{base_url}/ws"
        reply: dict[str, object]
        if payload["service"] == "sysbus.DeviceInfo":
            assert "Authorization" not in request.headers
            reply = {"status": {"ProductClass": "Livebox Fibre", "SoftwareVersion": "fixture"}}
        elif payload["service"] == "sah.Device.Information":
            assert request.headers["Authorization"] == "X-Sah-Login"
            assert payload["parameters"]["password"] == PASSWORD.get_secret_value()
            reply = {"data": {"contextID": "fixture-context"}}
        else:
            assert payload["service"] == "sysbus.Devices"
            assert payload["method"] == "get"
            assert request.headers["X-Context"] == "fixture-context"
            reply = {"status": [{"Name": "Synthetic device"}]}
        return httpx.Response(200, json={"result": reply} if wrapped else reply)

    snapshot = livebox5.read_snapshot(
        base_url,
        NETWORKS,
        PASSWORD,
        enabled=True,
        allow_http=allow_http,
        transport=httpx.MockTransport(handle),
    )
    assert snapshot.model == "Livebox 5"
    assert snapshot.firmware == "fixture"
    assert snapshot.devices == ({"Name": "Synthetic device"},)
    assert PASSWORD.get_secret_value() not in repr(snapshot)
    assert len(calls) == 3


def test_other_router_never_receives_password() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": {"ProductClass": "Other router"}})

    with pytest.raises(livebox5.LiveboxError, match="recognized Livebox 5"):
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(handle),
        )
    assert len(calls) == 1
    assert PASSWORD.get_secret_value().encode() not in calls[0].content


@pytest.mark.parametrize("status", [302, 401, 500])
def test_http_errors_and_redirects_are_refused(status: int) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://invalid.example"})

    with pytest.raises(livebox5.LiveboxError, match="HTTP"):
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(handle),
        )
    assert len(calls) == 1


@pytest.mark.parametrize("reply", [[], {"error": 1}, {"status": False}, {"result": []}])
def test_bad_replies_are_sanitized(reply: object) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=reply))
    with pytest.raises(livebox5.LiveboxError) as captured:
        livebox5.read_snapshot(
            "https://192.168.1.1", NETWORKS, PASSWORD, enabled=True, transport=transport
        )
    assert PASSWORD.get_secret_value() not in str(captured.value)


def test_response_size_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(livebox5, "MAX_RESPONSE_BYTES", 8)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 9))
    with pytest.raises(livebox5.LiveboxError, match="size limit"):
        livebox5.read_snapshot(
            "https://192.168.1.1", NETWORKS, PASSWORD, enabled=True, transport=transport
        )


def test_network_error_is_sanitized() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fixture transport detail", request=request)

    with pytest.raises(livebox5.LiveboxError, match="request or JSON") as captured:
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(handle),
        )
    assert "fixture transport detail" not in str(captured.value)


def test_mutating_operation_is_refused_without_http() -> None:
    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        pytest.raises(livebox5.LiveboxError, match="not allowed"),
    ):
        livebox5._post(client, "https://192.168.1.1/ws", "sysbus.Devices", "destroyDevice", {})


@pytest.mark.parametrize(
    "authentication",
    [{"status": False}, {"data": {}}, {"data": {"contextID": "bad\r\nvalue"}}],
)
def test_invalid_authentication_stops_before_device_read(authentication: object) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        reply = (
            {"status": {"ProductClass": "Livebox Fibre"}}
            if len(calls) == 1
            else authentication
        )
        return httpx.Response(200, json=reply)

    with pytest.raises(livebox5.LiveboxError):
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(handle),
        )
    assert len(calls) == 2


@pytest.mark.parametrize("devices", [None, [False], [{}] * 513])
def test_device_list_shape_and_count_are_checked(devices: object) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        service = json.loads(request.content)["service"]
        if service == "sysbus.DeviceInfo":
            return httpx.Response(200, json={"status": {"ProductClass": "Livebox Fibre"}})
        if service == "sah.Device.Information":
            return httpx.Response(200, json={"data": {"contextID": "fixture-context"}})
        return httpx.Response(200, json={"status": devices})

    with pytest.raises(livebox5.LiveboxError, match="device list"):
        livebox5.read_snapshot(
            "https://192.168.1.1",
            NETWORKS,
            PASSWORD,
            enabled=True,
            transport=httpx.MockTransport(handle),
        )
