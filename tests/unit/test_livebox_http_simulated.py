"""HTTP, real builder and temporary inventory; router traffic is simulated only."""

import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.db.connection import connect
from nettracker.db.migrations import migrate
from nettracker.db.repository import Repository
from nettracker.routers.control_service import LiveboxControlConfig, build_livebox_control
from nettracker.web.app import SECURITY_HEADERS, create_app
from nettracker.web.livebox_confirmations import PREFIX
from nettracker.web.livebox_results import FAILURE_DETAIL

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MAC = "02:00:00:00:00:20"
CREDENTIAL = "synthetic-http-builder-credential"
# Ephemeral test-only credential used exclusively with MockTransport.
PASSWORD = secrets.token_urlsafe(24)
CONTEXT = "synthetic-http-context"


@pytest.fixture(autouse=True)
def forbid_standard_network_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail("standard network transport is forbidden in simulated HTTP tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def seed(path: Path, ip: str = "192.168.1.20") -> int:
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW)
        repo.add_sighting(device_id=device.id, ip=ip, online=True, seen_at=NOW)
        return device.id
    finally:
        conn.close()


@dataclass
class Harness:
    app: FastAPI
    path: Path
    device_id: int
    methods: list[str]
    now: list[datetime]


def application(
    tmp_path: Path,
    *,
    blocked: bool = True,
    changed: bool = True,
    calendar_value: str = "Disable",
    failure: str = "",
    refusal: str = "",
) -> Harness:
    path = tmp_path / "inventory.db"
    device_id = 1 if refusal == "missing" else seed(path)
    now = [NOW]
    if refusal == "stale":
        now[0] += timedelta(seconds=61)
    elif refusal == "ambiguous":
        seed(path, "192.168.1.21")
    methods: list[str] = []
    desired = "Disable" if blocked else ""
    override = ("" if blocked else "Disable") if changed else desired

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal override
        assert request.url.host == "192.168.1.1"
        assert request.method == "POST"
        payload = json.loads(request.content)
        method = payload["method"]
        methods.append(method)
        if method == "get":
            assert payload["service"] == "sysbus.DeviceInfo"
            assert PASSWORD.encode() not in request.content
            firmware = "wrong-firmware" if failure == "firmware" else "synthetic-firmware"
            return httpx.Response(
                200, json={"status": {"ProductClass": "Livebox 5", "SoftwareVersion": firmware}}
            )
        if method == "createContext":
            assert payload["parameters"]["password"] == PASSWORD
            if failure == "auth":
                return httpx.Response(401, text="synthetic-private-detail")
            return httpx.Response(200, json={"data": {"contextID": CONTEXT}})
        assert payload["service"] == "sysbus.Scheduler"
        assert request.headers["X-Context"] == CONTEXT
        assert payload["parameters"]["ID"] == MAC
        assert method in {"getSchedule", "overrideSchedule"}
        if method == "overrideSchedule":
            assert payload["parameters"]["override"] == desired
            if failure == "uncertain":
                raise httpx.ReadTimeout("synthetic-private-detail", request=request)
            if failure != "readback":
                override = desired
            return httpx.Response(200, json={"status": True})
        value = "Disable" if override == "Disable" else calendar_value
        return httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "scheduleInfo": {"enable": True, "override": override, "value": value}
                },
            },
        )

    config = LiveboxControlConfig(
        database=path,
        base_url="https://192.168.1.1",
        networks=(IPv4Network("192.168.1.0/24"),),
        password=SecretStr(PASSWORD),
        expected_firmware="synthetic-firmware",
        management_mac=MAC if refusal == "protected" else "02:00:00:00:00:02",
        gateway_mac="02:00:00:00:00:03",
        enabled=refusal != "disabled",
    )
    guard = build_livebox_control(
        config, transport=httpx.MockTransport(handle), now=lambda: now[0]
    )
    assert methods == []
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(path),
            "api": {"token": CREDENTIAL},
        }
    )
    app = create_app(settings, livebox_guard=guard, livebox_control_enabled=True)
    assert methods == []
    return Harness(app, path, device_id, methods, now)


def field(text: str, name: str) -> str:
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', text)
    assert match is not None
    return match[1]


def login(client: TestClient) -> None:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"csrf": field(page.text, "csrf"), "token": CREDENTIAL},
        follow_redirects=False,
    )
    assert response.status_code == 303


def prepare(client: TestClient, harness: Harness, *, blocked: bool = True) -> httpx.Response:
    page = client.get(PREFIX)
    assert page.status_code == 200
    response = client.post(
        PREFIX + "/prepare",
        data={
            "csrf": field(page.text, "csrf"),
            "device_id": str(harness.device_id),
            "action": "block" if blocked else "release",
        },
    )
    assert harness.methods == []
    return response


def confirmation(response: httpx.Response) -> dict[str, str]:
    assert response.status_code == 200
    return {
        "csrf": field(response.text, "csrf"),
        "token": field(response.text, "token"),
        "confirm": "yes",
    }


def assert_headers_and_no_secrets(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    for secret in (CREDENTIAL, PASSWORD, CONTEXT, "synthetic-private-detail"):
        assert secret not in response.text


@pytest.mark.parametrize(
    ("blocked", "value"), [(True, "Disable"), (False, "Disable"), (False, "Enable")]
)
@pytest.mark.parametrize("changed", [True, False])
def test_http_builder_result_and_replay(
    tmp_path: Path, blocked: bool, value: str, changed: bool
) -> None:
    harness = application(tmp_path, blocked=blocked, changed=changed, calendar_value=value)
    with TestClient(harness.app) as client:
        login(client)
        data = confirmation(prepare(client, harness, blocked=blocked))
        response = client.post(PREFIX + "/confirm", data=data)
        assert response.status_code == 200
        assert_headers_and_no_secrets(response)
        assert (
            "Modification effectuée" if changed else "Etat déjà conforme, sans modification"
        ) in response.text
        assert ("Forçage de blocage présent" if blocked else "Aucun forçage") in response.text
        assert ("accès désactivé" if value == "Disable" else "accès activé") in response.text
        assert "ne prouve pas" in response.text
        expected = ["get", "createContext", "getSchedule"]
        if changed:
            expected += ["overrideSchedule", "getSchedule"]
        assert harness.methods == expected
        replay = client.post(PREFIX + "/confirm", data=data)
        assert replay.status_code == 409
        assert_headers_and_no_secrets(replay)
        assert harness.methods == expected


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("firmware", ["get"]),
        ("auth", ["get", "createContext"]),
        ("uncertain", ["get", "createContext", "getSchedule", "overrideSchedule"]),
        ("readback", ["get", "createContext", "getSchedule", "overrideSchedule", "getSchedule"]),
    ],
)
def test_http_adapter_failure_is_masked_and_consumed(
    tmp_path: Path, failure: str, expected: list[str]
) -> None:
    harness = application(tmp_path, failure=failure)
    with TestClient(harness.app) as client:
        login(client)
        data = confirmation(prepare(client, harness))
        for _ in range(2):
            response = client.post(PREFIX + "/confirm", data=data)
            assert response.status_code == 409
            assert response.json() == {"detail": FAILURE_DETAIL}
            assert_headers_and_no_secrets(response)
            assert harness.methods == expected
        assert harness.methods.count("overrideSchedule") <= 1


@pytest.mark.parametrize("refusal", ["disabled", "protected", "missing", "stale", "ambiguous"])
def test_http_prepare_refusal_never_reaches_adapter(tmp_path: Path, refusal: str) -> None:
    harness = application(tmp_path, refusal=refusal)
    with TestClient(harness.app) as client:
        login(client)
        response = prepare(client, harness)
        assert response.status_code == 409
        assert_headers_and_no_secrets(response)
        assert harness.methods == []
    if refusal == "missing":
        assert not harness.path.exists()


@pytest.mark.parametrize("change", ["stale", "ambiguous"])
def test_http_inventory_revalidation_consumes_without_adapter(
    tmp_path: Path, change: str
) -> None:
    harness = application(tmp_path)
    with TestClient(harness.app) as client:
        login(client)
        data = confirmation(prepare(client, harness))
        if change == "stale":
            harness.now[0] += timedelta(seconds=61)
        else:
            seed(harness.path, "192.168.1.21")
        for _ in range(2):
            response = client.post(PREFIX + "/confirm", data=data)
            assert response.status_code == 409
            assert response.json() == {"detail": FAILURE_DETAIL}
            assert_headers_and_no_secrets(response)
            assert harness.methods == []
