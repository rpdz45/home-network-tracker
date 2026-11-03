"""Dashboard refusal paths with synthetic inventory and no network executor."""

import re
from ipaddress import IPv4Address, IPv4Network

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.routers.control import AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.app import SECURITY_HEADERS, create_app
from nettracker.web.livebox_confirmations import PREFIX

CREDENTIAL = "synthetic-dashboard-refusal-credential"


def application() -> tuple[FastAPI, list[AccessRequest]]:
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
        {"allowed_subnets": ["192.168.1.0/24"], "api": {"token": CREDENTIAL}}
    )
    return create_app(settings, livebox_guard=guard, livebox_control_enabled=True), calls


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


@pytest.mark.parametrize(
    ("extra_headers", "suffix", "status"),
    [
        ({"Origin": "https://invalid.example"}, "", 403),
        ({"Sec-Fetch-Site": "cross-site"}, "", 403),
        ({"Content-Type": "application/json"}, "", 415),
        ({}, "&unexpected=yes", 422),
        ({}, "&device_id=2", 422),
        ({}, "&padding=" + "x" * 4096, 413),
    ],
)
def test_invalid_prepare_never_executes(
    extra_headers: dict[str, str], suffix: str, status: int
) -> None:
    app, calls = application()
    with TestClient(app) as client:
        login(client)
        page = client.get(PREFIX)
        csrf = field(page.text, "csrf")
        response = client.post(
            PREFIX + "/prepare",
            content=f"csrf={csrf}&device_id=1&action=block" + suffix,
            headers={"Content-Type": "application/x-www-form-urlencoded", **extra_headers},
        )
        assert response.status_code == status
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
        assert calls == []


def test_other_session_and_relogin_cannot_confirm_pending_request() -> None:
    app, calls = application()
    with TestClient(app) as first, TestClient(app) as second:
        login(first)
        login(second)
        page = first.get(PREFIX)
        prepared = first.post(
            PREFIX + "/prepare",
            data={"csrf": field(page.text, "csrf"), "device_id": "1", "action": "block"},
        )
        assert prepared.status_code == 200
        data = {
            "csrf": field(prepared.text, "csrf"),
            "token": field(prepared.text, "token"),
            "confirm": "yes",
        }
        denied = second.post(PREFIX + "/confirm", data=data)
        assert denied.status_code == 403
        for name, value in SECURITY_HEADERS.items():
            assert denied.headers[name] == value
        page = first.get("/logout")
        response = first.post(
            "/logout", data={"csrf": field(page.text, "csrf")}, follow_redirects=False
        )
        assert response.status_code == 303
        assert first.post(PREFIX + "/confirm", data=data).status_code == 403
        login(first)
        assert first.post(PREFIX + "/confirm", data=data).status_code == 403
        assert calls == []
