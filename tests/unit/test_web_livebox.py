"""Livebox form tests use simulated readers and synthetic credentials only."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.routers import livebox5
from nettracker.web.app import create_app

TOKEN = "dashboard-fixture-token"
PASSWORD = "synthetic-livebox-password"


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "NETTRACKER_LIVEBOX5_ENABLED", "NETTRACKER_LIVEBOX5_URL",
        "NETTRACKER_LIVEBOX5_PASSWORD", "NETTRACKER_LIVEBOX5_ALLOW_HTTP",
    ):
        monkeypatch.delenv(key, raising=False)

    def forbidden(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        pytest.fail("Unexpected network reader invocation")

    monkeypatch.setattr(livebox5, "read_snapshot", forbidden)


def client_for(tmp_path: Path, *, token: bool = True) -> TestClient:
    settings = Settings.model_validate({
        "allowed_subnets": ["192.168.1.0/24"],
        "database_path": str(tmp_path / "unused.db"),
        "api": {"token": TOKEN} if token else {},
    })
    client = TestClient(create_app(settings))
    if token:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
    return client


def enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_URL", "https://192.168.1.1")


def form(client: TestClient) -> dict[str, str]:
    page = client.get("/routers/livebox")
    assert page.status_code == 200
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', page.text)
    assert match is not None
    return {"csrf": match[1], "confirm": "yes", "username": "admin", "password": PASSWORD}


def test_default_is_inert(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        page = client.get("/routers/livebox")
        assert page.status_code == 200
        assert "<form" not in page.text
        assert client.post("/routers/livebox/read", data={}).status_code == 403
    assert not (tmp_path / "unused.db").exists()


def test_form_available_without_environment_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable(monkeypatch)
    with client_for(tmp_path) as client:
        page = client.get("/routers/livebox")
        assert 'type="password"' in page.text
        assert 'value="admin"' in page.text
        assert page.headers["cache-control"] == "no-store"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert PASSWORD not in page.text


@pytest.mark.parametrize("case", ["disabled", "missing-address", "outside-subnet", "http"])
def test_configuration_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    enable(monkeypatch)
    if case == "disabled":
        monkeypatch.delenv("NETTRACKER_LIVEBOX5_ENABLED")
    elif case == "missing-address":
        monkeypatch.delenv("NETTRACKER_LIVEBOX5_URL")
    elif case == "outside-subnet":
        monkeypatch.setenv("NETTRACKER_LIVEBOX5_URL", "https://192.168.2.1")
    else:
        monkeypatch.setenv("NETTRACKER_LIVEBOX5_URL", "http://192.168.1.1")
    with client_for(tmp_path) as client:
        assert "<form" not in client.get("/routers/livebox").text
        assert client.post("/routers/livebox/read", data={}).status_code == 403


def test_authentication_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    with client_for(tmp_path, token=False) as client:
        assert "<form" not in client.get("/routers/livebox").text
        assert client.post("/routers/livebox/read", data={}).status_code == 403
    with client_for(tmp_path) as client:
        client.headers.pop("Authorization")
        assert client.get("/routers/livebox", follow_redirects=False).status_code == 303
        client.headers["Authorization"] = "Bearer incorrect"
        assert client.post("/routers/livebox/read", data={}).status_code == 401


@pytest.mark.parametrize(
    ("change", "status"),
    [({"csrf": "incorrect"}, 403), ({"confirm": "no"}, 422),
     ({"username": "other"}, 422), ({"password": ""}, 422), ({"extra": "x"}, 422)],
)
def test_invalid_forms_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, str], status: int
) -> None:
    enable(monkeypatch)
    with client_for(tmp_path) as client:
        data = form(client)
        data.update(change)
        assert client.post("/routers/livebox/read", data=data).status_code == status


@pytest.mark.parametrize("headers", [{"Origin": "https://invalid.example"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cross_site_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    enable(monkeypatch)
    with client_for(tmp_path) as client:
        assert client.post("/routers/livebox/read", data=form(client), headers=headers).status_code == 403


@pytest.mark.parametrize("legacy", [False, True])
def test_password_read_redaction_and_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    enable(monkeypatch)
    if legacy:
        monkeypatch.setenv("NETTRACKER_LIVEBOX5_PASSWORD", PASSWORD)
    calls: list[str] = []

    def read(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        assert args[0] == "https://192.168.1.1"
        assert isinstance(args[2], SecretStr)
        calls.append(args[2].get_secret_value())
        assert kwargs == {"enabled": True, "allow_http": False}
        return livebox5.LiveboxSnapshot(
            "Livebox 5", PASSWORD,
            ({"Name": "<script>x</script>" + PASSWORD, "Active": True},),
        )

    monkeypatch.setattr(livebox5, "read_snapshot", read)
    with client_for(tmp_path) as client:
        data = form(client)
        if legacy:
            data = {key: data[key] for key in ("csrf", "confirm")}
        response = client.post("/routers/livebox/read", data=data)
        assert response.status_code == 200
        assert calls == [PASSWORD]
        assert PASSWORD not in response.text
        assert "<script>x</script>" not in response.text
        assert "&lt;script&gt;x&lt;/script&gt;" in response.text
        assert "[masqué]" in response.text
        assert "Actif selon la box" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/routers/livebox/read", data=data).status_code == 429
        assert calls == [PASSWORD]
    assert not (tmp_path / "unused.db").exists()


def test_errors_hide_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)

    def fail(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        raise livebox5.LiveboxError(PASSWORD)

    monkeypatch.setattr(livebox5, "read_snapshot", fail)
    with client_for(tmp_path) as client:
        response = client.post("/routers/livebox/read", data=form(client))
        assert response.status_code == 503
        assert PASSWORD not in response.text
        assert "Lecture impossible" in response.text


def test_media_size_and_duplicate_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    with client_for(tmp_path) as client:
        assert client.post("/routers/livebox/read", json={}).status_code == 415
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        assert client.post("/routers/livebox/read", content=b"x=" + b"a" * 4096, headers=headers).status_code == 413
        assert client.post("/routers/livebox/read", content=b"csrf=x&confirm=yes&csrf=y", headers=headers).status_code == 422
