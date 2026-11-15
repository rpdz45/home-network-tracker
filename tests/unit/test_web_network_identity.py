"""Stored DNS rendering, escaping and binding checks without DNS traffic."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.db.network_identity import IdentityObservation, save_observations
from nettracker.web.app import create_app

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


@pytest.mark.parametrize("scenario", ["empty", "name", "timeout", "escaped", "changed"])
def test_dns_detail_is_readonly_and_never_queries_dns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    path = tmp_path / "web.db"
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device("02:00:00:00:00:20", seen_at=NOW)
        repo.add_sighting(device_id=device.id, ip="192.168.1.20", online=True, seen_at=NOW)
        conn.execute("UPDATE devices SET alias = 'My NAS' WHERE id = ?", (device.id,))
        value = "<script>dns</script>" if scenario == "escaped" else "nas.test"
        if scenario != "empty":
            observation = IdentityObservation(
                "hostname",
                "dns_ptr",
                "192.168.1.1",
                None if scenario == "timeout" else value,
                NOW,
                "timeout" if scenario == "timeout" else "reported",
            )
            save_observations(
                conn,
                device_id=device.id,
                matched_mac=device.mac,
                matched_ip="192.168.1.20",
                observations=(observation,),
                confirmed=True,
                now=NOW,
            )
        if scenario == "changed":
            conn.execute("UPDATE sightings SET ip = '192.168.1.21'")
        before = tuple(conn.iterdump())
    finally:
        conn.close()

    def forbidden(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        pytest.fail("viewing the page must not query DNS")

    monkeypatch.setattr("nettracker.discovery.router_dns._query_ptr", forbidden)
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": path}
    )
    with TestClient(create_app(settings, clock=lambda: NOW)) as client:
        response = client.get(f"/devices/{device.id}")
    assert response.status_code == 200
    assert "Noms DNS enregistrés" in response.text
    assert "<h1>My NAS</h1>" in response.text
    if scenario in ("empty", "changed"):
        assert "Aucune observation DNS enregistrée" in response.text
        assert "nas.test" not in response.text
    elif scenario == "timeout":
        assert "Délai dépassé" in response.text
    elif scenario == "escaped":
        assert "&lt;script&gt;dns&lt;/script&gt;" in response.text
        assert "<script>dns</script>" not in response.text
    else:
        assert "nas.test" in response.text
        assert "192.168.1.1" in response.text
    conn = connect(path)
    try:
        assert tuple(conn.iterdump()) == before
    finally:
        conn.close()
