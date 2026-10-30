"""Storage HTTP tests use the real app and SQLite, with no Fing transport."""

import re
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.discovery import fing
from nettracker.web.app import create_app

MAC = "02:00:00:00:00:01"


def field(html: str, name: str) -> str:
    match = re.search(r'name="' + name + r'" value="([a-f0-9]+)"', html)
    assert match is not None
    return match[1]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NETTRACKER_FING_ENABLED", "true")
    monkeypatch.setenv("NETTRACKER_FING_API_KEY", "synthetic-api-key")
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "storage.db"),
            "api": {"token": "synthetic-dashboard-token"},
        }
    )
    with closing(connect(settings.database_path)) as conn:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=datetime.now(UTC))
        repo.add_sighting(
            device_id=device.id, ip="192.168.1.10", online=True, seen_at=datetime.now(UTC)
        )

    def read(*args: object, **kwargs: object) -> fing.FingInventory:
        assert isinstance(args[0], SecretStr)
        return fing.FingInventory(
            "synthetic-network",
            datetime.now(UTC),
            (fing.FingDevice(MAC, ("192.168.1.10",), "Test", "Brand", "Model", "PC", "UP"),),
            0,
        )

    monkeypatch.setattr(fing, "read_inventory", read)
    return TestClient(
        create_app(settings), headers={"Authorization": "Bearer synthetic-dashboard-token"}
    )


def preview(client: TestClient) -> dict[str, str]:
    csrf = field(client.get("/identification/fing").text, "csrf")
    response = client.post("/identification/fing/read", data={"csrf": csrf, "confirm": "yes"})
    assert response.status_code == 200
    return {"csrf": csrf, "confirm": "yes", "preview": field(response.text, "preview")}


def test_confirmed_store_is_local_and_cannot_be_replayed(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = preview(client)

    def forbidden(*args: object, **kwargs: object) -> fing.FingInventory:
        pytest.fail("store must not call Fing")

    monkeypatch.setattr(fing, "read_inventory", forbidden)
    response = client.post("/identification/fing/store", data=data)
    assert response.status_code == 200
    assert "Stockage terminé" in response.text
    assert client.post("/identification/fing/store", data=data).status_code == 409
    with closing(connect(tmp_path / "storage.db")) as conn:
        row = conn.execute("SELECT manufacturer, model FROM device_identifications").fetchone()
        assert tuple(row) == ("Brand", "Model")
        assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("change", "headers", "status"),
    [
        ({"csrf": "bad"}, {}, 403),
        ({"confirm": "no"}, {}, 422),
        ({"model": "forged"}, {}, 422),
        ({"preview": "bad"}, {}, 409),
        ({}, {"Origin": "https://invalid.example"}, 403),
        ({}, {"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_invalid_store_changes_nothing(
    client: TestClient,
    tmp_path: Path,
    change: dict[str, str],
    headers: dict[str, str],
    status: int,
) -> None:
    data = preview(client)
    data.update(change)
    assert (
        client.post("/identification/fing/store", data=data, headers=headers).status_code == status
    )
    with closing(connect(tmp_path / "storage.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_identifications").fetchone()[0] == 0


def test_store_requires_dashboard_authentication(client: TestClient) -> None:
    data = preview(client)
    client.headers.pop("Authorization")
    assert (
        client.post("/identification/fing/store", data=data, follow_redirects=False).status_code
        == 303
    )


def test_old_api_result_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def old(*args: object, **kwargs: object) -> fing.FingInventory:
        return fing.FingInventory(
            "synthetic-network", datetime.now(UTC) - timedelta(minutes=11), (), 0
        )

    monkeypatch.setattr(fing, "read_inventory", old)
    assert client.post("/identification/fing/store", data=preview(client)).status_code == 409
