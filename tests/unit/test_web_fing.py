"""Fing web tests use the real app, synthetic identities and a replaced reader."""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.discovery import fing
from nettracker.web import fing_dashboard
from nettracker.web.app import create_app

CREDENTIAL = "synthetic-dashboard-credential"
API_FIXTURE = "synthetic-not-a-real-fing-key"
MAC = "02:00:00:00:00:01"


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ["NETTRACKER_FING_ENABLED", "NETTRACKER_FING_API_KEY"]:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> fing.FingInventory:
        pytest.fail("unexpected Fing connection")

    monkeypatch.setattr(fing, "read_inventory", forbidden)


def activate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETTRACKER_FING_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_FING_API_KEY", API_FIXTURE)


def local_rows() -> list[sqlite3.Row]:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT 1 AS id, ? AS mac, '192.168.1.10' AS ip, ? AS alias, 'host' AS hostname",
            (MAC, "Mon PC " + API_FIXTURE),
        ).fetchall()


def inventory() -> fing.FingInventory:
    return fing.FingInventory(
        "synthetic-network",
        datetime(2026, 1, 1, tzinfo=UTC),
        (
            fing.FingDevice(
                MAC,
                ("192.168.1.10",),
                "<script>x</script>",
                "Fixture brand",
                None,
                "DESKTOP",
                "UP",
            ),
        ),
        2,
    )


def client_for(tmp_path: Path, *, token: bool = True) -> TestClient:
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "test.db"),
            "api": {"token": CREDENTIAL} if token else {},
        }
    )
    client = TestClient(create_app(settings))
    if token:
        client.headers["Authorization"] = f"Bearer {CREDENTIAL}"
    return client


def form(client: TestClient) -> dict[str, str]:
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', client.get("/identification/fing").text)
    assert match is not None
    return {"csrf": match[1], "confirm": "yes"}


def test_default_get_does_not_create_database(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.get("/identification/fing")
        assert response.status_code == 200
        assert "Lecture Fing désactivée" in response.text
        assert "<form" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post("/identification/fing/read", data={}).status_code == 403
    assert not (tmp_path / "test.db").exists()


@pytest.mark.parametrize("missing", ["NETTRACKER_FING_ENABLED", "NETTRACKER_FING_API_KEY"])
def test_missing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    activate(monkeypatch)
    monkeypatch.delenv(missing)
    with client_for(tmp_path) as client:
        assert "<form" not in client.get("/identification/fing").text
        assert client.post("/identification/fing/read", data={}).status_code == 403


def test_authentication_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with client_for(tmp_path, token=False) as client:
        assert "<form" not in client.get("/identification/fing").text
        assert client.post("/identification/fing/read", data={}).status_code == 403
    with client_for(tmp_path) as client:
        client.headers.pop("Authorization")
        assert client.get("/identification/fing", follow_redirects=False).status_code == 303
        client.headers["Authorization"] = "Bearer wrong"
        assert client.post("/identification/fing/read", data={}).status_code == 401


@pytest.mark.parametrize(
    ("change", "headers", "status"),
    [
        ({"csrf": "wrong"}, {}, 403),
        ({"confirm": "no"}, {}, 422),
        ({"api_key": "injected"}, {}, 422),
        ({}, {"Origin": "https://invalid.example"}, 403),
        ({}, {"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_invalid_requests_do_not_load_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, str],
    headers: dict[str, str],
    status: int,
) -> None:
    activate(monkeypatch)
    with client_for(tmp_path) as client:
        data = form(client)
        data.update(change)
        response = client.post("/identification/fing/read", data=data, headers=headers)
        assert response.status_code == status
    assert not (tmp_path / "test.db").exists()


def test_body_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with client_for(tmp_path) as client:
        assert client.post("/identification/fing/read", json={}).status_code == 415
        response = client.post(
            "/identification/fing/read",
            content="x=" + "a" * 2048,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413


def test_display_matching_and_cooldown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    calls: list[dict[str, object]] = []
    records = local_rows()
    monkeypatch.setattr(fing_dashboard, "_load_rows", lambda _: records)

    def read(*args: object, **kwargs: object) -> fing.FingInventory:
        assert isinstance(args[0], SecretStr)
        assert args[0].get_secret_value() == API_FIXTURE
        calls.append(kwargs)
        return inventory()

    monkeypatch.setattr(fing, "read_inventory", read)
    with client_for(tmp_path) as client:
        data = form(client)
        response = client.post("/identification/fing/read", data=data)
        assert response.status_code == 200
        assert API_FIXTURE not in response.text
        assert "&lt;script&gt;x&lt;/script&gt;" in response.text
        assert "<script>x</script>" not in response.text
        assert "Mon PC [masqué]" in response.text
        assert "Fixture brand" in response.text
        assert "Non identifié" in response.text
        assert 'href="/devices/1"' in response.text
        assert "Ce n'est pas la date du dernier scan" in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert calls == [{"enabled": True, "confirmed": True}]
        assert client.post("/identification/fing/read", data=data).status_code == 429
        assert len(calls) == 1
    assert records[0]["alias"] == "Mon PC " + API_FIXTURE
    assert not (tmp_path / "test.db").exists()


def test_missing_database_prevents_fing_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(monkeypatch)
    with client_for(tmp_path) as client:
        response = client.post("/identification/fing/read", data=form(client))
        assert response.status_code == 503
        assert API_FIXTURE not in response.text
    assert not (tmp_path / "test.db").exists()


def test_reader_failure_is_not_echoed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    monkeypatch.setattr(fing_dashboard, "_load_rows", lambda _: local_rows())

    def fail(*args: object, **kwargs: object) -> fing.FingInventory:
        raise fing.FingError(API_FIXTURE)

    monkeypatch.setattr(fing, "read_inventory", fail)
    with client_for(tmp_path) as client:
        response = client.post("/identification/fing/read", data=form(client))
        assert response.status_code == 503
        assert API_FIXTURE not in response.text


def test_ambiguous_local_match_has_no_link() -> None:
    rows = local_rows()
    result = fing_dashboard.identity_rows(inventory(), rows + rows, API_FIXTURE)
    assert result[0].local_id is None
    assert "ambiguë" in result[0].association


def test_ip_or_mac_alone_does_not_match() -> None:
    original = inventory()
    other = fing.FingDevice(MAC, ("192.168.1.20",), None, None, None, None, "DOWN")
    changed = fing.FingInventory(original.network_id, original.retrieved_at, (other,), 0)
    result = fing_dashboard.identity_rows(changed, local_rows(), API_FIXTURE)
    assert result[0].local_id is None
    assert result[0].model == "Non identifié"


def test_link_from_devices_without_fing_enabled(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "test.db")) as connection:
        migrate(connection)
    with client_for(tmp_path) as client:
        assert 'href="/identification/fing"' in client.get("/").text
