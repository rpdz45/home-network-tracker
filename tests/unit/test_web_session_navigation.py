"""Session-aware navigation on the actual dashboard, without a database."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.web.app import COOKIE_NAME, create_app

CREDENTIAL = "synthetic-navigation-credential"


def settings(path: Path, *, authenticated: bool = True) -> Settings:
    return Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(path),
            "api": {"token": CREDENTIAL} if authenticated else {},
        }
    )


def test_logout_navigation_requires_a_browser_session(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    with TestClient(create_app(settings(path))) as client:
        page = client.get("/routers", headers={"Authorization": f"Bearer {CREDENTIAL}"})
        assert page.status_code == 200
        assert 'href="/logout"' not in page.text
        login = client.get("/login")
        match = re.search(r'name="csrf" value="([a-f0-9]+)"', login.text)
        assert match is not None
        response = client.post(
            "/login", data={"csrf": match[1], "token": CREDENTIAL},
            follow_redirects=False,
        )
        assert response.status_code == 303
        session = client.cookies[COOKIE_NAME]
        page = client.get("/routers")
        assert page.status_code == 200
        assert 'href="/logout"' in page.text
        assert session not in page.text
        assert CREDENTIAL not in page.text
        confirmation = client.get("/logout")
        assert confirmation.status_code == 200
        assert 'method="post" action="/logout"' in confirmation.text
        assert client.get("/routers").status_code == 200
        assert confirmation.headers["cache-control"] == "no-store"
        assert confirmation.headers["content-security-policy"].startswith("default-src 'none'")
    assert not path.exists()


def test_no_credential_means_no_logout_navigation(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    with TestClient(create_app(settings(path, authenticated=False))) as client:
        page = client.get("/routers")
        assert page.status_code == 200
        assert 'href="/logout"' not in page.text
    assert not path.exists()
