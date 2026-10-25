"""Authenticated device editing with an in-process client and real SQLite migrations."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.web.app import create_app

CREDENTIAL = "device-edit-test-credential"


def make_client(tmp_path: Path, *, authenticated: bool = True) -> TestClient:
    api = {"token": CREDENTIAL} if authenticated else {}
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "edit.db"),
            "api": api,
        }
    )
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        Repository(conn).upsert_device(
            "02:00:00:00:00:01", seen_at=datetime.now(UTC), hostname="fixture-phone"
        )
    finally:
        conn.close()
    client = TestClient(create_app(settings))
    if authenticated:
        client.headers["Authorization"] = f"Bearer {CREDENTIAL}"
    return client


def form(client: TestClient) -> dict[str, str]:
    page = client.get("/devices/1")
    assert page.status_code == 200
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', page.text)
    assert match is not None
    return {"csrf": match[1], "alias": "Fixture NAS", "device_type": "nas"}


def test_edit_persists_and_can_mark_known(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = form(client)
    data["mark_known"] = "yes"
    response = client.post("/devices/1/edit", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/devices/1"
    page = client.get("/devices/1").text
    assert "Fixture NAS" in page
    assert "known" in page


def test_no_token_keeps_dashboard_readonly(tmp_path: Path) -> None:
    client = make_client(tmp_path, authenticated=False)
    assert 'name="csrf"' not in client.get("/devices/1").text
    assert client.post("/devices/1/edit", data={}).status_code == 403


def test_missing_and_wrong_authentication_cannot_write(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = form(client)
    client.headers.pop("Authorization")
    assert client.post("/devices/1/edit", data=data, follow_redirects=False).status_code == 303
    client.headers["Authorization"] = "Bearer wrong"
    assert client.post("/devices/1/edit", data=data).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://invalid.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_writes_are_refused(tmp_path: Path, headers: dict[str, str]) -> None:
    client = make_client(tmp_path)
    assert client.post("/devices/1/edit", data=form(client), headers=headers).status_code == 403


def test_bad_csrf_is_refused(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = form(client)
    data["csrf"] = "wrong"
    assert client.post("/devices/1/edit", data=data).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [{"device_type": "invalid"}, {"alias": "a" * 121}, {"mark_known": "no"}, {"extra": "field"}],
)
def test_invalid_fields_do_not_change_device(tmp_path: Path, changes: dict[str, str]) -> None:
    client = make_client(tmp_path)
    data = form(client)
    data.update(changes)
    assert client.post("/devices/1/edit", data=data).status_code == 422
    assert "Fixture NAS" not in client.get("/devices/1").text


def test_body_limit_and_content_type(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/devices/1/edit", json={}).status_code == 415
    response = client.post(
        "/devices/1/edit",
        content="a=" + "x" * 4096,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413


def test_cookie_authenticated_form_and_empty_alias(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.headers.pop("Authorization")
    assert client.post("/login", data={"token": CREDENTIAL}).status_code == 200
    data = form(client)
    data["alias"] = ""
    data["device_type"] = ""
    assert client.post("/devices/1/edit", data=data).status_code == 200
    assert "fixture-phone" in client.get("/").text


def test_ignored_approval_rolls_back_identity(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    conn = connect(tmp_path / "edit.db")
    try:
        Repository(conn).set_status(1, "ignored")
    finally:
        conn.close()
    data = form(client)
    data["mark_known"] = "yes"
    assert client.post("/devices/1/edit", data=data).status_code == 422
    assert "Fixture NAS" not in client.get("/devices/1").text


def test_alias_is_html_escaped(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    data = form(client)
    data["alias"] = "<script>alert(1)</script>"
    response = client.post("/devices/1/edit", data=data)
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
