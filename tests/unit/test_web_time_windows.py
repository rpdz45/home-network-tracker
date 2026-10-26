"""HTTP history validation with real migrations and stored fixtures; no network probes."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.monitoring import MonitoringRepository
from nettracker.web.app import create_app

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
CREDENTIAL = "time-window-fixture-credential"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "time-http.db"
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(path),
            "api": {"token": CREDENTIAL},
        }
    )
    conn = connect(path)
    try:
        migrate(conn)
        repo = MonitoringRepository(conn)
        device = repo.upsert_device("02:00:00:00:00:01", seen_at=NOW - timedelta(days=8))
        repo.add_sighting(
            device_id=device.id,
            ip="192.168.1.20",
            online=True,
            seen_at=NOW - timedelta(days=8),
        )
        target = repo.target(device.id)
        repo.record(
            target,
            online=True,
            latency_ms=3.0,
            packet_loss_pct=0.0,
            checked_at=NOW - timedelta(days=3),
        )
        for index in range(30):
            online = index % 3 != 0
            repo.record(
                target,
                online=online,
                latency_ms=1.0 if online else None,
                packet_loss_pct=0.0 if online else 100.0,
                checked_at=NOW - timedelta(hours=2) + timedelta(seconds=index),
            )
        for index in range(30):
            repo.add_sighting(
                device_id=device.id,
                ip="192.168.1.20",
                online=True,
                seen_at=NOW - timedelta(hours=1) + timedelta(seconds=index),
            )
        other = repo.upsert_device("02:00:00:00:00:02", seen_at=NOW - timedelta(hours=1))
        repo.add_sighting(
            device_id=other.id,
            ip="192.168.1.21",
            online=True,
            seen_at=NOW - timedelta(hours=1),
        )
        repo.record(
            repo.target(other.id),
            online=True,
            latency_ms=999.0,
            packet_loss_pct=0.0,
            checked_at=NOW - timedelta(minutes=30),
        )
        repo.upsert_device("02:00:00:00:00:03", seen_at=NOW, hostname="empty-fixture")
    finally:
        conn.close()
    with TestClient(create_app(settings, clock=lambda: NOW)) as browser:
        browser.headers["Authorization"] = f"Bearer {CREDENTIAL}"
        yield browser


def snapshot(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def test_default_window_is_24h_and_ignores_discovery_limit(client: TestClient) -> None:
    response = client.get("/devices/1")
    assert response.status_code == 200
    assert 'value="24h" selected' in response.text
    assert "20 réponse(s) sur 30 mesure(s)" in response.text
    assert "66.7 %" in response.text
    assert response.text.count('class="history-slot"') == 96
    assert "999.0" not in response.text


def test_seven_days_includes_older_ping(client: TestClient) -> None:
    response = client.get("/devices/1", params={"window": "7d"})
    assert response.status_code == 200
    assert 'value="7d" selected' in response.text
    assert "21 réponse(s) sur 31 mesure(s)" in response.text
    assert "67.7 %" in response.text
    assert "105 minutes" in response.text


@pytest.mark.parametrize("window", ["", "24H", "30d", "../", "<script>"])
def test_invalid_windows_are_rejected(client: TestClient, window: str) -> None:
    assert client.get("/devices/1", params={"window": window}).status_code == 422


def test_unknown_device_returns_404_for_valid_window(client: TestClient) -> None:
    assert client.get("/devices/999", params={"window": "7d"}).status_code == 404


def test_other_device_has_its_own_ratio_not_temporal_uptime(client: TestClient) -> None:
    response = client.get("/devices/2", params={"window": "24h"})
    assert response.status_code == 200
    assert "1 réponse(s) sur 1 mesure(s)" in response.text
    assert "pas un uptime temporel" in response.text


def test_window_pages_preserve_security_headers(client: TestClient) -> None:
    response = client.get("/devices/1", params={"window": "7d"})
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert CREDENTIAL not in response.text


def test_history_requires_authentication(client: TestClient) -> None:
    client.headers.pop("Authorization")
    response = client.get("/devices/1?window=7d", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    client.headers["Authorization"] = "Bearer wrong"
    assert client.get("/devices/1?window=7d").status_code == 401


def test_history_gets_do_not_change_database(client: TestClient, tmp_path: Path) -> None:
    before = snapshot(tmp_path / "time-http.db")
    for window in ("24h", "7d"):
        assert client.get("/devices/1", params={"window": window}).status_code == 200
    assert snapshot(tmp_path / "time-http.db") == before


def test_empty_device_has_unknown_history(client: TestClient) -> None:
    response = client.get("/devices/3", params={"window": "7d"})
    assert response.status_code == 200
    assert "Aucune mesure ICMP dans cette fenêtre. Disponibilité inconnue." in response.text
    assert "réponse(s) sur" not in response.text
    assert response.text.count('class="history-slot"') == 96


def test_history_also_accepts_login_cookie(client: TestClient) -> None:
    client.headers.pop("Authorization")
    response = client.post("/login", data={"token": CREDENTIAL}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/devices/1?window=7d").status_code == 200
