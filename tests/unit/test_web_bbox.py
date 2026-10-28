"""Bbox dashboard tests use the real application and a simulated reader."""

import re
from ipaddress import IPv4Network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.routers import bbox, bbox_session
from nettracker.web import bbox_dashboard
from nettracker.web.app import create_app

CREDENTIAL = "synthetic-dashboard-credential"
ADMIN_FIXTURE = "fixture-not-a-real-bbox-password"
ADDRESS = "https://192.168.1.254"
MODEL = "synthetic-bbox-model"
VARIABLES = (
    "NETTRACKER_BBOX_AUTH_ENABLED",
    "NETTRACKER_BBOX_URL",
    "NETTRACKER_BBOX_ALLOW_HTTP",
    "NETTRACKER_BBOX_PASSWORD",
    "NETTRACKER_BBOX_EXPECTED_MODEL",
    "NETTRACKER_BBOX_CA_FILE",
)


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> bbox_session.BboxSnapshot:
        pytest.fail("unexpected Bbox connection")

    monkeypatch.setattr(bbox_session, "read_authenticated_snapshot", forbidden)


def activate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETTRACKER_BBOX_AUTH_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_BBOX_URL", ADDRESS)
    monkeypatch.setenv("NETTRACKER_BBOX_PASSWORD", ADMIN_FIXTURE)
    monkeypatch.setenv("NETTRACKER_BBOX_EXPECTED_MODEL", MODEL)


def make_client(*, token: bool = True) -> TestClient:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "api": {"token": CREDENTIAL} if token else {}}
    )
    client = TestClient(create_app(settings))
    if token:
        client.headers["Authorization"] = f"Bearer {CREDENTIAL}"
    return client


def form(client: TestClient) -> dict[str, str]:
    response = client.get("/routers/bbox")
    assert response.status_code == 200
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', response.text)
    assert match is not None
    return {"csrf": match[1], "confirm": "yes"}


def test_default_is_inert() -> None:
    with make_client() as client:
        response = client.get("/routers/bbox")
        assert "Lecture désactivée" in response.text
        assert "<form" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post("/routers/bbox/read", data={}).status_code == 403


@pytest.mark.parametrize("missing", VARIABLES[:2] + VARIABLES[3:5])
def test_missing_configuration_blocks_login(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    activate(monkeypatch)
    monkeypatch.delenv(missing)
    with make_client() as client:
        response = client.get("/routers/bbox")
        assert "<form" not in response.text
        assert ADMIN_FIXTURE not in response.text
        assert client.post("/routers/bbox/read", data={}).status_code == 403


def test_dashboard_token_required(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with make_client(token=False) as client:
        assert "<form" not in client.get("/routers/bbox").text
        assert client.post("/routers/bbox/read", data={}).status_code == 403
    with make_client() as client:
        client.headers.pop("Authorization")
        assert client.get("/routers/bbox", follow_redirects=False).status_code == 303
        response = client.post("/routers/bbox/read", data={}, follow_redirects=False)
        assert response.status_code == 303
        client.headers["Authorization"] = "Bearer wrong"
        assert client.post("/routers/bbox/read", data={}).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://invalid.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_refused(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    activate(monkeypatch)
    with make_client() as client:
        response = client.post("/routers/bbox/read", data=form(client), headers=headers)
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("changes", "status"),
    [({"csrf": "wrong"}, 403), ({"confirm": "no"}, 422), ({"password": "injected"}, 422)],
)
def test_forms_cannot_change_server_configuration(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str], status: int
) -> None:
    activate(monkeypatch)
    with make_client() as client:
        data = form(client)
        data.update(changes)
        assert client.post("/routers/bbox/read", data=data).status_code == status


def test_reader_parameters_escaping_and_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    clock = [1000.0]
    monkeypatch.setattr(bbox_dashboard, "monotonic", lambda: clock[0])
    monkeypatch.setenv("NETTRACKER_BBOX_CA_FILE", "synthetic-ca.pem")

    def read(*args: object, **kwargs: object) -> bbox_session.BboxSnapshot:
        calls.append((args, kwargs))
        assert isinstance(args[2], SecretStr)
        assert args[2].get_secret_value() == ADMIN_FIXTURE
        return bbox_session.BboxSnapshot(
            MODEL,
            ADMIN_FIXTURE,
            (
                bbox_session.BboxHost(
                    1,
                    "<script>x</script> " + ADMIN_FIXTURE,
                    None,
                    "02:00:00:00:00:01",
                    True,
                    None,
                ),
            ),
            False,
        )

    monkeypatch.setattr(bbox_session, "read_authenticated_snapshot", read)
    with make_client() as client:
        data = form(client)
        response = client.post("/routers/bbox/read", data=data)
        assert response.status_code == 200
        assert ADMIN_FIXTURE not in response.text
        assert "<script>x</script>" not in response.text
        assert "&lt;script&gt;x&lt;/script&gt;" in response.text
        assert "[masqué]" in response.text
        assert "Non renseigné" in response.text
        assert "Actif selon la box" in response.text
        assert "Déconnexion non confirmée" in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert calls[0][0][0] == ADDRESS
        assert calls[0][0][1] == [IPv4Network("192.168.1.0/24")]
        assert calls[0][0][3] == MODEL
        assert calls[0][1] == {
            "enabled": True,
            "confirmed": True,
            "allow_http": False,
            "ca_file": Path("synthetic-ca.pem"),
        }
        clock[0] = 1600.0
        assert client.post("/routers/bbox/read", data=data).status_code == 429
        clock[0] = 1901.0
        assert client.post("/routers/bbox/read", data=data).status_code == 200
        assert len(calls) == 2


def test_failure_redacts_and_consumes_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)

    def fail(*args: object, **kwargs: object) -> bbox_session.BboxSnapshot:
        raise bbox.BboxError(ADMIN_FIXTURE)

    monkeypatch.setattr(bbox_session, "read_authenticated_snapshot", fail)
    with make_client() as client:
        data = form(client)
        response = client.post("/routers/bbox/read", data=data)
        assert response.status_code == 503
        assert ADMIN_FIXTURE not in response.text
        assert "Lecture Bbox impossible" in response.text
        assert client.post("/routers/bbox/read", data=data).status_code == 429


def test_media_type_size_and_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with make_client() as client:
        assert client.post("/routers/bbox/read", json={}).status_code == 415
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = client.post(
            "/routers/bbox/read", content="x=" + "a" * 2048, headers=headers
        )
        assert response.status_code == 413
        response = client.post("/routers/bbox/read", content="csrf=x&csrf=y", headers=headers)
        assert response.status_code == 422


def test_http_requires_explicit_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    monkeypatch.setenv("NETTRACKER_BBOX_URL", "http://192.168.1.254")
    with make_client() as client:
        assert "<form" not in client.get("/routers/bbox").text
        assert client.post("/routers/bbox/read", data={}).status_code == 403
    monkeypatch.setenv("NETTRACKER_BBOX_ALLOW_HTTP", "true")
    with make_client() as client:
        response = client.get("/routers/bbox")
        assert "échanges non chiffrés" in response.text
        assert form(client)["confirm"] == "yes"


def test_application_registers_bbox(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "absent.db"),
            "api": {"token": CREDENTIAL},
        }
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/routers/bbox", follow_redirects=False).status_code == 303
        client.headers["Authorization"] = f"Bearer {CREDENTIAL}"
        assert client.get("/routers/bbox").status_code == 200
        assert 'href="/routers/bbox"' in client.get("/routers").text
        assert client.get("/routers/bbox").headers["Cache-Control"] == "no-store"
    assert not (tmp_path / "absent.db").exists()
