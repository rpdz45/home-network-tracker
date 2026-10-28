"""Livebox dashboard tests replace the reader; no router or secret is real."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.routers import livebox5
from nettracker.web.app import create_app

CREDENTIAL = "livebox-dashboard-test-credential"
ADMIN_FIXTURE = "fixture-not-a-real-livebox-password"
ADDRESS = "https://192.168.1.1"


@pytest.fixture(autouse=True)
def isolate_livebox(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "NETTRACKER_LIVEBOX5_ENABLED",
        "NETTRACKER_LIVEBOX5_URL",
        "NETTRACKER_LIVEBOX5_ALLOW_HTTP",
        "NETTRACKER_LIVEBOX5_PASSWORD",
    ]:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        pytest.fail("unexpected Livebox read")

    monkeypatch.setattr(livebox5, "read_snapshot", forbidden)


def activate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_URL", ADDRESS)
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_PASSWORD", ADMIN_FIXTURE)


def make_client(tmp_path: Path, *, authenticated: bool = True) -> TestClient:
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "not-created.db"),
            "api": {"token": CREDENTIAL} if authenticated else {},
        }
    )
    client = TestClient(create_app(settings))
    if authenticated:
        client.headers["Authorization"] = f"Bearer {CREDENTIAL}"
    return client


def form(client: TestClient) -> dict[str, str]:
    response = client.get("/routers/livebox")
    assert response.status_code == 200
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', response.text)
    assert match is not None
    return {"csrf": match[1], "confirm": "yes"}


def test_default_page_is_inert(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/routers/livebox")
        assert response.status_code == 200
        assert "Lecture désactivée" in response.text
        assert "<form" not in response.text
        assert client.post("/routers/livebox/read", data={}).status_code == 403
        assert 'href="/routers/livebox"' in client.get("/routers").text
    assert not (tmp_path / "not-created.db").exists()


@pytest.mark.parametrize("missing", ["NETTRACKER_LIVEBOX5_PASSWORD", "NETTRACKER_LIVEBOX5_URL"])
def test_missing_configuration_prevents_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    activate(monkeypatch)
    monkeypatch.delenv(missing)
    with make_client(tmp_path) as client:
        response = client.get("/routers/livebox")
        assert "<form" not in response.text
        assert ADMIN_FIXTURE not in response.text
        assert client.post("/routers/livebox/read", data={}).status_code == 403


def test_no_dashboard_token_prevents_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with make_client(tmp_path, authenticated=False) as client:
        assert "<form" not in client.get("/routers/livebox").text
        assert client.post("/routers/livebox/read", data={}).status_code == 403


def test_existing_authentication_is_preserved(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.headers.pop("Authorization")
        assert client.get("/routers/livebox", follow_redirects=False).status_code == 303
        client.headers["Authorization"] = "Bearer wrong"
        assert client.post("/routers/livebox/read", data={}).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://invalid.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_reads_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        response = client.post("/routers/livebox/read", data=form(client), headers=headers)
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("changes", "expected"),
    [({"csrf": "wrong"}, 403), ({"confirm": "no"}, 422), ({"target": "other"}, 422)],
)
def test_invalid_forms_never_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, str],
    expected: int,
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        data = form(client)
        data.update(changes)
        assert client.post("/routers/livebox/read", data=data).status_code == expected


def test_reader_uses_secret_and_redacts_display_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def read(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        calls.append((args, kwargs))
        assert isinstance(args[2], SecretStr)
        assert args[2].get_secret_value() == ADMIN_FIXTURE
        return livebox5.LiveboxSnapshot(
            "Livebox 5",
            ADMIN_FIXTURE,
            (
                {
                    "Name": "<script>x</script> " + ADMIN_FIXTURE,
                    "Active": True,
                    "Other": ADMIN_FIXTURE,
                },
            ),
        )

    monkeypatch.setattr(livebox5, "read_snapshot", read)
    with make_client(tmp_path) as client:
        data = form(client)
        response = client.post("/routers/livebox/read", data=data)
        assert response.status_code == 200
        assert ADMIN_FIXTURE not in response.text
        assert "<script>x</script>" not in response.text
        assert "&lt;script&gt;x&lt;/script&gt;" in response.text
        assert "[masqué]" in response.text
        assert "Non renseigné" in response.text
        assert "Actif selon la box" in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert calls[0][0][0] == ADDRESS
        assert calls[0][1] == {"enabled": True, "allow_http": False}
        assert client.post("/routers/livebox/read", data=data).status_code == 429
        assert len(calls) == 1


def test_errors_do_not_echo_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)

    def fail(*args: object, **kwargs: object) -> livebox5.LiveboxSnapshot:
        raise livebox5.LiveboxError(ADMIN_FIXTURE)

    monkeypatch.setattr(livebox5, "read_snapshot", fail)
    with make_client(tmp_path) as client:
        response = client.post("/routers/livebox/read", data=form(client))
        assert response.status_code == 503
        assert ADMIN_FIXTURE not in response.text
        assert "Lecture Livebox impossible" in response.text


def test_body_size_and_media_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        assert client.post("/routers/livebox/read", json={}).status_code == 415
        response = client.post(
            "/routers/livebox/read",
            content="x=" + "a" * 2048,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413


def test_http_requires_server_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_URL", "http://192.168.1.1")
    with make_client(tmp_path) as client:
        assert "<form" not in client.get("/routers/livebox").text
        assert client.post("/routers/livebox/read", data={}).status_code == 403
    monkeypatch.setenv("NETTRACKER_LIVEBOX5_ALLOW_HTTP", "true")
    with make_client(tmp_path) as client:
        response = client.get("/routers/livebox")
        assert "ne sont pas chiffrés" in response.text
        assert ADMIN_FIXTURE not in response.text
        assert form(client)["confirm"] == "yes"
