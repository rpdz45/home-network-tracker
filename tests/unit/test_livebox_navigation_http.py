"""HTTP navigation through real login, with synthetic inventory and no box access."""

import re
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.routers.control import AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.app import COOKIE_NAME, SECURITY_HEADERS, create_app
from nettracker.web.livebox_confirmations import PREFIX

CREDENTIAL = "synthetic-http-navigation-credential"


def field(text: str, name: str) -> str:
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', text)
    assert match is not None
    return match[1]


@pytest.mark.parametrize("enabled", [False, True])
def test_livebox_navigation_after_login_and_logout(tmp_path: Path, enabled: bool) -> None:
    path = tmp_path / "absent.db"
    calls: list[AccessRequest] = []
    guard = ControlGuards[None](
        lambda device, blocked: AccessRequest(
            RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
        ),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(path),
            "api": {"token": CREDENTIAL},
        }
    )
    app = create_app(settings, livebox_guard=guard, livebox_control_enabled=enabled)
    link = f'href="{PREFIX}"'
    bearer = {"Authorization": f"Bearer {CREDENTIAL}"}
    with TestClient(app) as client:
        anonymous = client.get("/routers", follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"] == "/login"
        page = client.get("/routers", headers=bearer)
        assert page.status_code == 200
        assert link not in page.text
        login_page = client.get("/login")
        response = client.post(
            "/login",
            data={"csrf": field(login_page.text, "csrf"), "token": CREDENTIAL},
            follow_redirects=False,
        )
        assert response.status_code == 303
        session = client.cookies[COOKIE_NAME]
        page = client.get("/routers")
        assert page.status_code == 200
        assert (link in page.text) == enabled
        assert session not in page.text
        assert CREDENTIAL not in page.text
        control_page = client.get(PREFIX)
        assert control_page.status_code == (200 if enabled else 404)
        if enabled:
            assert f'action="{PREFIX}/prepare"' in control_page.text
            for name, value in SECURITY_HEADERS.items():
                assert control_page.headers[name] == value
        assert calls == []
        bearer_page = client.get("/routers", headers=bearer)
        assert bearer_page.status_code == 200
        assert link not in bearer_page.text
        denied = client.get(PREFIX, headers=bearer)
        assert denied.status_code == (403 if enabled else 404)
        logout_page = client.get("/logout")
        response = client.post(
            "/logout", data={"csrf": field(logout_page.text, "csrf")}, follow_redirects=False
        )
        assert response.status_code == 303
        assert COOKIE_NAME not in client.cookies
        assert client.get("/routers", follow_redirects=False).status_code == 303
        assert client.get(PREFIX).status_code == (403 if enabled else 404)
        assert calls == []
    assert not path.exists()


def test_unconfigured_dashboard_has_no_livebox_link(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": str(path)}
    )
    with TestClient(create_app(settings)) as client:
        page = client.get("/routers")
        assert page.status_code == 200
        assert f'href="{PREFIX}"' not in page.text
        assert client.get(PREFIX).status_code == 404
    assert not path.exists()
