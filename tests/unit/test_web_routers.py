"""Router dashboard actions use a replaced reader, never a real router."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.routers import bbox
from nettracker.web.app import create_app

CREDENTIAL = "router-dashboard-test-credential"
ADDRESS = "https://192.168.1.254"


@pytest.fixture(autouse=True)
def isolate_router(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "NETTRACKER_BBOX_DIAGNOSTICS_ENABLED",
        "NETTRACKER_BBOX_URL",
        "NETTRACKER_BBOX_ALLOW_HTTP",
    ]:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> tuple[bbox.EndpointProbe, ...]:
        pytest.fail("unexpected router diagnostic")

    monkeypatch.setattr(bbox, "read_diagnostic", forbidden)


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


def activate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETTRACKER_BBOX_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_BBOX_URL", ADDRESS)


def form(client: TestClient) -> dict[str, str]:
    response = client.get("/routers")
    assert response.status_code == 200
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', response.text)
    assert match is not None
    return {"csrf": match[1], "confirm": "yes"}


def test_default_page_is_inert_without_database(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/routers")
        assert response.status_code == 200
        assert "Diagnostic désactivé" in response.text
        assert 'href="/routers"' in response.text
        assert '<form' not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post("/routers/bbox/diagnose", data={}).status_code == 403
    assert not (tmp_path / "not-created.db").exists()


def test_enabled_get_still_never_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        assert form(client)["confirm"] == "yes"
        assert "Blocage et déblocage indisponibles" in client.get("/routers").text


def test_missing_dashboard_token_cannot_diagnose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path, authenticated=False) as client:
        assert '<form' not in client.get("/routers").text
        assert client.post("/routers/bbox/diagnose", data={}).status_code == 403


def test_existing_authentication_is_required(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.headers.pop("Authorization")
        response = client.get("/routers", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        client.headers["Authorization"] = "Bearer wrong"
        assert client.post("/routers/bbox/diagnose", data={}).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://invalid.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_diagnostics_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        response = client.post("/routers/bbox/diagnose", data=form(client), headers=headers)
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("changes", "expected"),
    [({"csrf": "wrong"}, 403), ({"confirm": "no"}, 422), ({"extra": "value"}, 422)],
)
def test_invalid_forms_do_not_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, str],
    expected: int,
) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        data = form(client)
        data.update(changes)
        assert client.post("/routers/bbox/diagnose", data=data).status_code == expected


def test_body_limit_and_content_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with make_client(tmp_path) as client:
        assert client.post("/routers/bbox/diagnose", json={}).status_code == 415
        response = client.post(
            "/routers/bbox/diagnose",
            content="x=" + "a" * 2048,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413


def test_success_uses_server_target_and_limits_repeated_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def read(*args: object, **kwargs: object) -> tuple[bbox.EndpointProbe, ...]:
        calls.append((args, kwargs))
        return (bbox.EndpointProbe("/api/v1/device", bbox.ProbeState.AUTH_REQUIRED),)

    monkeypatch.setattr(bbox, "read_diagnostic", read)
    with make_client(tmp_path) as client:
        data = form(client)
        response = client.post("/routers/bbox/diagnose", data=data)
        assert response.status_code == 200
        assert "Authentification ou droits requis" in response.text
        assert CREDENTIAL not in response.text
        assert calls[0][0][0] == ADDRESS
        assert calls[0][1] == {"enabled": True, "allow_http": False}
        assert client.post("/routers/bbox/diagnose", data=data).status_code == 429
        assert len(calls) == 1


def test_reader_errors_are_not_rendered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)

    def fail(*args: object, **kwargs: object) -> tuple[bbox.EndpointProbe, ...]:
        raise bbox.BboxError("private diagnostic detail")

    monkeypatch.setattr(bbox, "read_diagnostic", fail)
    with make_client(tmp_path) as client:
        response = client.post("/routers/bbox/diagnose", data=form(client))
        assert response.status_code == 503
        assert "Diagnostic impossible" in response.text
        assert "private diagnostic detail" not in response.text


def test_invalid_target_is_not_rendered_or_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    monkeypatch.setenv("NETTRACKER_BBOX_URL", "<script>bad</script>")
    with make_client(tmp_path) as client:
        response = client.get("/routers")
        assert "<script>bad</script>" not in response.text
        assert "&lt;script&gt;bad&lt;/script&gt;" not in response.text
        assert "Adresse Bbox invalide" in response.text
        assert '<form' not in response.text
        assert client.post("/routers/bbox/diagnose", data={}).status_code == 403
