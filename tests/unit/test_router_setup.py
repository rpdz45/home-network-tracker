"""Browser setup tests use synthetic adapter results, never real router traffic."""

import re
import secrets
from ipaddress import IPv4Network
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.routers import bbox, bbox_session, livebox5
from nettracker.web.app import SECURITY_HEADERS, create_app
from nettracker.web.router_setup import PREFIX

CREDENTIAL = secrets.token_urlsafe(24)


def field(text: str, name: str) -> str:
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', text)
    assert match is not None
    return match[1]


def client_for(tmp_path: Path, *, authenticated: bool = True) -> TestClient:
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "absent.db"),
            "api": {"token": CREDENTIAL if authenticated else None},
        }
    )
    return TestClient(create_app(settings))


def login(client: TestClient) -> None:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"csrf": field(page.text, "csrf"), "token": CREDENTIAL},
        follow_redirects=False,
    )
    assert response.status_code == 303


def form(client: TestClient, *, kind: str = "livebox5") -> dict[str, str]:
    page = client.get(PREFIX)
    assert page.status_code == 200
    return {
        "csrf": field(page.text, "csrf"),
        "kind": kind,
        "address": "https://192.168.1.1",
        "model": "synthetic-model" if kind == "bbox" else "",
        "allow_http": "no",
        "password": secrets.token_urlsafe(24),
        "confirm": "yes",
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail("real network transport is forbidden")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


@pytest.mark.parametrize("kind", ["livebox5", "bbox"])
def test_explicit_read_without_environment_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    calls: list[str] = []

    def livebox_read(
        address: str, networks: list[IPv4Network], password: SecretStr, **kwargs: object
    ) -> livebox5.LiveboxSnapshot:
        calls.append(address)
        assert kwargs == {"enabled": True, "allow_http": False}
        assert password.get_secret_value()
        return livebox5.LiveboxSnapshot(
            "Livebox 5",
            "synthetic",
            ({"Name": "<b>Salon</b>", "IPAddress": "192.168.1.20", "Active": True},),
        )

    def bbox_read(
        address: str,
        networks: list[IPv4Network],
        password: SecretStr,
        model: str,
        **kwargs: object,
    ) -> bbox_session.BboxSnapshot:
        calls.append(address)
        assert model == "synthetic-model"
        assert kwargs == {"enabled": True, "confirmed": True, "allow_http": False}
        return bbox_session.BboxSnapshot(
            model,
            "synthetic",
            (
                bbox_session.BboxHost(
                    1, "<b>Salon</b>", "192.168.1.20", "02:00:00:00:00:20", True, None
                ),
            ),
            True,
        )

    monkeypatch.delenv("NETTRACKER_LIVEBOX5_ENABLED", raising=False)
    monkeypatch.delenv("NETTRACKER_BBOX_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(livebox5, "read_snapshot", livebox_read)
    monkeypatch.setattr(bbox_session, "read_authenticated_snapshot", bbox_read)
    with client_for(tmp_path) as client:
        login(client)
        assert 'href="/routers/setup"' in client.get("/routers").text
        data = form(client, kind=kind)
        assert calls == []
        response = client.post(PREFIX + "/read", data=data)
        assert response.status_code == 200
        assert calls == ["https://192.168.1.1"]
        assert "&lt;b&gt;Salon&lt;/b&gt;" in response.text
        assert "<b>Salon</b>" not in response.text
        assert data["password"] not in response.text
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
        assert client.post(PREFIX + "/read", data=data).status_code == 429
        assert len(calls) == 1
    assert not (tmp_path / "absent.db").exists()


@pytest.mark.parametrize(
    ("updates", "status"),
    [
        ({"csrf": "wrong"}, 403),
        ({"confirm": "no"}, 422),
        ({"address": "https://8.8.8.8"}, 422),
        ({"address": "https://192.168.2.1"}, 422),
        ({"address": "https://admin:secret@192.168.1.1"}, 422),
        ({"address": "http://192.168.1.1"}, 422),
        ({"kind": "bbox", "model": ""}, 422),
        ({"kind": "unknown"}, 422),
    ],
)
def test_invalid_requests_do_not_reach_network(
    tmp_path: Path, updates: dict[str, str], status: int
) -> None:
    with client_for(tmp_path) as client:
        login(client)
        data = form(client)
        response = client.post(PREFIX + "/read", data={**data, **updates})
        assert response.status_code == status


def test_browser_session_and_same_origin_are_required(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.get(PREFIX, follow_redirects=False).status_code == 303
        login(client)
        data = form(client)
        denied = client.get(PREFIX, headers={"Authorization": f"Bearer {CREDENTIAL}"})
        assert denied.status_code == 403
        denied = client.post(
            PREFIX + "/read", data=data, headers={"Origin": "https://invalid.example"}
        )
        assert denied.status_code == 403
        assert client.post(PREFIX + "/read", data={**data, "extra": "yes"}).status_code == 422
    with client_for(tmp_path, authenticated=False) as client:
        assert client.get(PREFIX).status_code == 403


@pytest.mark.parametrize("kind", ["livebox5", "bbox"])
def test_adapter_error_is_generic_and_password_not_redisplayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise bbox.BboxError("synthetic-private-detail")

    monkeypatch.setattr(livebox5, "read_snapshot", fail)
    monkeypatch.setattr(bbox_session, "read_authenticated_snapshot", fail)
    with client_for(tmp_path) as client:
        login(client)
        data = form(client, kind=kind)
        response = client.post(PREFIX + "/read", data=data)
        assert response.status_code == 503
        assert "synthetic-private-detail" not in response.text
        assert data["password"] not in response.text
        assert client.post(PREFIX + "/read", data=data).status_code == 429
