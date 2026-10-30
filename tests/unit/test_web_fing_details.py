"""Stored Fing reports are historical, escaped and read without network calls."""

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
def no_fing_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETTRACKER_FING_ENABLED", raising=False)
    monkeypatch.delenv("NETTRACKER_FING_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> fing.FingInventory:
        pytest.fail("device details must not read Fing")

    monkeypatch.setattr(fing, "read_inventory", forbidden)


def seed(path: Path, *, saved: bool = True, model: str | None = "Fixture model") -> int:
    with closing(connect(path)) as conn:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW, vendor="Interface vendor")
        conn.execute("UPDATE devices SET alias = 'Mon appareil' WHERE id = ?", (device.id,))
        repo.add_sighting(device_id=device.id, ip="192.168.1.10", online=True, seen_at=NOW)
        if saved:
            report = fing.FingDevice(
                MAC, ("192.168.1.10",), "Reported name", "Reported maker", model, "PC", "UP"
            )
            inventory = fing.FingInventory("synthetic-network", NOW, (report,), 0)
            settings = Settings.model_validate({"allowed_subnets": ["192.168.1.0/24"]})
            summary = save_fing_inventory(
                conn, inventory, settings.allowed_subnets, confirmed=True, now=NOW
            )
            assert summary.stored == 1
        return device.id


def page(path: Path, device_id: int) -> str:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": str(path)}
    )
    with TestClient(create_app(settings, clock=lambda: NOW)) as client:
        response = client.get(f"/devices/{device_id}")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.text


def snapshot(path: Path) -> tuple[str, ...]:
    with closing(connect(path)) as conn:
        return tuple(conn.iterdump())


def test_saved_report_is_visible_without_configuring_fing(tmp_path: Path) -> None:
    path = tmp_path / "details.db"
    device_id = seed(path)
    before = snapshot(path)
    text = page(path, device_id)
    assert "Identification Fing enregistrée" in text
    assert "Fixture model" in text
    assert "Reported maker" in text
    assert "Reported name" in text
    assert "Interface vendor" in text
    assert "<h1>Mon appareil</h1>" in text
    assert "13:00 · 15/01/2026" in text
    assert "déclaration non vérifiée indépendamment" in text
    assert "pas une garantie de l'IP actuelle" in text
    assert snapshot(path) == before


def test_missing_report_does_not_invent_a_model(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    text = page(path, seed(path, saved=False))
    assert "Aucune identification Fing enregistrée" in text
    assert "Identification Fing enregistrée</h2>" not in text


def test_missing_model_stays_unidentified(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    text = page(path, seed(path, model=None))
    assert "Identification Fing enregistrée" in text
    assert "Non identifié" in text


def test_reported_html_is_escaped(tmp_path: Path) -> None:
    path = tmp_path / "escaped.db"
    text = page(path, seed(path, model="<script>fixture()</script>"))
    assert "&lt;script&gt;fixture()&lt;/script&gt;" in text
    assert "<script>fixture()</script>" not in text


@pytest.mark.parametrize("change", ["merged", "mac"])
def test_no_report_for_merged_or_changed_identity(tmp_path: Path, change: str) -> None:
    path = tmp_path / "changed.db"
    device_id = seed(path)
    with closing(connect(path)) as conn:
        if change == "merged":
            other = Repository(conn).upsert_device("02:00:00:00:00:02", seen_at=NOW)
            conn.execute("UPDATE devices SET merged_into = ? WHERE id = ?", (other.id, device_id))
        else:
            conn.execute(
                "UPDATE devices SET mac = '02:00:00:00:00:03' WHERE id = ?", (device_id,)
            )
    assert "Identification Fing enregistrée</h2>" not in page(path, device_id)
