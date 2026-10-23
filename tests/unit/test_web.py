"""Tests for the read-only dashboard (in-process client, no real network)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.web.app import COOKIE_NAME, create_app
from nettracker.web.queries import open_readonly

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
CREDENTIAL = "correct-horse-battery-staple"
XSS = "<script>alert(1)</script>"
FORM = {"content-type": "application/x-www-form-urlencoded"}


def make_settings(tmp_path: Path, credential: str | None = None) -> Settings:
    api: dict[str, str] = {"host": "127.0.0.1"}
    if credential is not None:
        api["token"] = credential
    return Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "web-test.db"),
            "api": api,
        }
    )


def seed(path: Path) -> None:
    conn = connect(path)
    try:
        migrate(conn)
        repo = Repository(conn)
        phone = repo.upsert_device("aa:bb:cc:dd:ee:01", seen_at=NOW, hostname="phone")
        repo.upsert_device("aa:bb:cc:dd:ee:02", seen_at=NOW, hostname=XSS)
        ghost = repo.upsert_device("aa:bb:cc:dd:ee:03", seen_at=NOW, hostname="ghost")
        conn.execute("UPDATE devices SET merged_into = ? WHERE id = ?", (phone.id, ghost.id))
        repo.add_sighting(device_id=phone.id, ip="192.168.1.20", online=True, seen_at=NOW)
        event = repo.add_event("new_device", created_at=NOW, device_id=phone.id)
        repo.add_notification(event_id=event, channel="dry-run", status="dry_run", sent_at=NOW)
        scan = repo.start_scan(mode="passive", started_at=NOW)
        repo.finish_scan(scan, status="ok", finished_at=NOW, devices_found=2)
    finally:
        conn.close()


def make_client(
    tmp_path: Path, credential: str | None = None, now: datetime = NOW
) -> TestClient:
    settings = make_settings(tmp_path, credential)
    seed(settings.database_path)
    return TestClient(create_app(settings, clock=lambda: now))


def test_devices_page_lists_unmerged_devices(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/")
    assert response.status_code == 200
    assert "aa:bb:cc:dd:ee:01" in response.text
    assert "192.168.1.20" in response.text
    assert "ghost" not in response.text


def test_hostnames_are_escaped(tmp_path: Path) -> None:
    text = make_client(tmp_path).get("/").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>alert(1)" not in text


def test_device_detail_shows_measures_and_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/devices/1")
    assert response.status_code == 200
    assert "phone" in response.text
    assert "new_device" in response.text
    assert "dry_run" in response.text


def test_unknown_or_malformed_device_ids_are_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/devices/999").status_code == 404
    assert client.get("/devices/abc").status_code == 422


def test_events_page_shows_the_notification_status(tmp_path: Path) -> None:
    text = make_client(tmp_path).get("/events").text
    assert "new_device" in text
    assert "dry_run" in text


def test_collector_health_is_ok_then_stale(tmp_path: Path) -> None:
    assert "Collecteur : OK" in make_client(tmp_path).get("/").text
    later = NOW + timedelta(hours=2)
    assert "Collecteur : périmé" in make_client(tmp_path, now=later).get("/").text


def test_security_headers_and_no_documentation_endpoints(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/")
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_the_dashboard_has_no_write_route(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/").status_code == 405
    assert client.delete("/devices/1").status_code == 405


def test_the_database_connection_refuses_writes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed(settings.database_path)
    conn = open_readonly(settings.database_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM devices")
    finally:
        conn.close()


def test_an_uninitialised_database_gives_a_503_without_paths(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    sqlite3.connect(settings.database_path).close()
    response = TestClient(create_app(settings)).get("/")
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


def test_without_credentials_the_browser_is_sent_to_the_login_page(tmp_path: Path) -> None:
    response = make_client(tmp_path, CREDENTIAL).get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_a_bearer_credential_is_checked(tmp_path: Path) -> None:
    client = make_client(tmp_path, CREDENTIAL)
    wrong = client.get("/", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = client.get("/", headers={"Authorization": f"Bearer {CREDENTIAL}"})
    assert right.status_code == 200


def test_login_sets_a_strict_http_only_cookie(tmp_path: Path) -> None:
    client = make_client(tmp_path, CREDENTIAL)
    bad = client.post("/login", content="token=wrong", headers=FORM, follow_redirects=False)
    assert bad.status_code == 401
    assert COOKIE_NAME not in bad.cookies
    content = f"token={CREDENTIAL}"
    good = client.post("/login", content=content, headers=FORM, follow_redirects=False)
    assert good.status_code == 303
    cookie = good.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    page = client.get("/")
    assert page.status_code == 200
    assert CREDENTIAL not in page.text


def test_the_login_form_is_public_and_oversized_bodies_are_refused(tmp_path: Path) -> None:
    client = make_client(tmp_path, CREDENTIAL)
    assert "Jeton" in client.get("/login").text
    big = client.post("/login", content="token=" + "x" * 10_000, headers=FORM)
    assert big.status_code == 413


def test_login_is_not_needed_without_a_configured_credential(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
