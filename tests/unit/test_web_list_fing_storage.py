"""Exercise stored Fing reports through SQLite and the real device list route."""

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.db.identifications import save_fing_inventory
from nettracker.discovery import fing
from nettracker.web.app import create_app

NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
MAC = "02:00:00:00:00:01"


@pytest.fixture(autouse=True)
def forbid_fing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETTRACKER_FING_ENABLED", raising=False)
    monkeypatch.delenv("NETTRACKER_FING_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> fing.FingInventory:
        pytest.fail("GET device list must not read Fing")

    monkeypatch.setattr(fing, "read_inventory", forbidden)


def seed(path: Path, *, saved: bool = True, model: str | None = "Fixture model") -> int:
    with closing(connect(path)) as conn:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW, vendor="Interface vendor")
        conn.execute("UPDATE devices SET alias = 'Personal alias' WHERE id = ?", (device.id,))
        repo.add_sighting(device_id=device.id, ip="192.168.1.10", online=True, seen_at=NOW)
        if saved:
            report = fing.FingDevice(
                MAC, ("192.168.1.10",), "Reported name", "Reported maker", model, "PC", "UP"
            )
            inventory = fing.FingInventory("synthetic-network", NOW, (report,), 0)
            settings = Settings.model_validate({"allowed_subnets": ["192.168.1.0/24"]})
            result = save_fing_inventory(
                conn, inventory, settings.allowed_subnets, confirmed=True, now=NOW
            )
            assert result.stored == 1
        return device.id


def snapshot(path: Path) -> tuple[str, ...]:
    with closing(connect(path)) as conn:
        return tuple(conn.iterdump())


def page(path: Path) -> str:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": str(path)}
    )
    before = snapshot(path)
    with TestClient(create_app(settings, clock=lambda: NOW)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert snapshot(path) == before
    return response.text


def test_list_loads_stored_report_and_preserves_alias(tmp_path: Path) -> None:
    path = tmp_path / "list.db"
    device_id = seed(path)
    text = page(path)
    assert f'href="/devices/{device_id}">Personal alias</a>' in text
    for value in ("Fixture model", "Reported maker", "Reported name", "Interface vendor"):
        assert value in text
    assert "13:00 · 15/01/2026" in text
    assert "déclaration historique, non vérifiée indépendamment" in text
    assert text.count(f'href="/devices/{device_id}"') == 1


def test_list_without_report_does_not_invent_identification(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    seed(path, saved=False)
    text = page(path)
    assert "Aucune identification enregistrée" in text
    assert "Fixture model" not in text
    assert "Reported maker" not in text
    assert "Interface vendor" in text


@pytest.mark.parametrize("model", [None, "<script>fixture()</script>"])
def test_list_handles_missing_or_untrusted_model(tmp_path: Path, model: str | None) -> None:
    path = tmp_path / "model.db"
    seed(path, model=model)
    text = page(path)
    if model is None:
        assert "Modèle : Non identifié" in text
    else:
        assert model not in text
        assert "&lt;script&gt;fixture()&lt;/script&gt;" in text


@pytest.mark.parametrize("change", ["mac", "merged"])
def test_list_hides_report_after_identity_change(tmp_path: Path, change: str) -> None:
    path = tmp_path / "changed.db"
    device_id = seed(path)
    with closing(connect(path)) as conn:
        if change == "mac":
            conn.execute("UPDATE devices SET mac = '02:00:00:00:00:03' WHERE id = ?", (device_id,))
        else:
            other = Repository(conn).upsert_device("02:00:00:00:00:02", seen_at=NOW)
            conn.execute("UPDATE devices SET merged_into = ? WHERE id = ?", (other.id, device_id))
    text = page(path)
    assert "Fixture model" not in text
    assert "Reported name" not in text
    assert "Reported maker" not in text
    if change == "merged":
        assert f'href="/devices/{device_id}"' not in text
    else:
        assert "Personal alias" in text
        assert "Aucune identification enregistrée" in text
