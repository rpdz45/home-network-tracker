"""Real dashboard wiring with a synthetic target and an in-memory executor only."""

import re
from ipaddress import IPv4Address, IPv4Network

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.routers.control import AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.app import SECURITY_HEADERS, create_app
from nettracker.web.livebox_confirmations import PREFIX

CREDENTIAL = "synthetic-dashboard-integration-credential"


def settings(*, authenticated: bool = True) -> Settings:
    return Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "api": {"token": CREDENTIAL if authenticated else None},
        }
    )


def guard(calls: list[AccessRequest]) -> ControlGuards[None]:
    return ControlGuards[None](
        lambda device, blocked: AccessRequest(
            RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
        ),
        calls.append,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
    )


def field(text: str, name: str) -> str:
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', text)
    assert match is not None
    return match[1]


def login(client: TestClient) -> None:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"csrf": field(page.text, "csrf"), "token": CREDENTIAL},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_routes_absent_by_default_even_with_guard() -> None:
    calls: list[AccessRequest] = []
    for app in [create_app(settings()), create_app(settings(), livebox_guard=guard(calls))]:
        with TestClient(app) as client:
            assert client.get(PREFIX).status_code == 404
            assert client.post(PREFIX + "/prepare").status_code == 404
            assert client.post(PREFIX + "/confirm").status_code == 404
    assert calls == []


def test_enable_requires_credential_and_guard() -> None:
    with pytest.raises(ValueError, match="requires a credential"):
        create_app(settings(), livebox_control_enabled=True)
    with pytest.raises(ValueError, match="requires a credential"):
        create_app(
            settings(authenticated=False), livebox_guard=guard([]), livebox_control_enabled=True
        )


def test_dashboard_sessions_confirm_once_and_security_headers_cover_errors() -> None:
    calls: list[AccessRequest] = []
    app = create_app(settings(), livebox_guard=guard(calls), livebox_control_enabled=True)
    with TestClient(app) as client:
        denied = client.get(PREFIX)
        assert denied.status_code == 403
        for name, value in SECURITY_HEADERS.items():
            assert denied.headers[name] == value
        login(client)
        denied = client.get(PREFIX, headers={"Authorization": f"Bearer {CREDENTIAL}"})
        assert denied.status_code == 403
        page = client.get(PREFIX)
        assert page.status_code == 200
        prepared = client.post(
            PREFIX + "/prepare",
            data={"csrf": field(page.text, "csrf"), "device_id": "1", "action": "block"},
        )
        assert prepared.status_code == 200
        assert calls == []
        data = {
            "csrf": field(prepared.text, "csrf"),
            "token": field(prepared.text, "token"),
            "confirm": "yes",
        }
        denied = client.post(PREFIX + "/confirm", data={**data, "csrf": "wrong"})
        assert denied.status_code == 403
        assert calls == []
        response = client.post(PREFIX + "/confirm", data=data)
        assert response.status_code == 200
        assert len(calls) == 1
        replay = client.post(PREFIX + "/confirm", data=data)
        assert replay.status_code == 409
        for name, value in SECURITY_HEADERS.items():
            assert replay.headers[name] == value
        page = client.get("/logout")
        assert (
            client.post(
                "/logout", data={"csrf": field(page.text, "csrf")}, follow_redirects=False
            ).status_code
            == 303
        )
        assert client.get(PREFIX).status_code == 403
        assert len(calls) == 1
