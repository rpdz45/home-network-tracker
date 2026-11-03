"""Shared Livebox page templates with an in-memory executor, never a real box."""

import re
from ipaddress import IPv4Address, IPv4Network

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nettracker.config import Settings
from nettracker.routers.control import AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.app import COOKIE_NAME, SECURITY_HEADERS, TEMPLATES_DIR, create_app
from nettracker.web.livebox_confirmations import PREFIX

CREDENTIAL = "synthetic-template-credential"


def field(text: str, name: str) -> str:
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]+)"', text)
    assert match is not None
    return match[1]


def test_all_stages_share_navigation_without_exposing_session() -> None:
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
    app = create_app(settings, livebox_guard=guard, livebox_control_enabled=True)
    with TestClient(app) as client:
        login = client.get("/login")
        response = client.post(
            "/login",
            data={"csrf": field(login.text, "csrf"), "token": CREDENTIAL},
            follow_redirects=False,
        )
        assert response.status_code == 303
        session = client.cookies[COOKIE_NAME]
        page = client.get(PREFIX)
        assert page.status_code == 200
        prepared = client.post(
            PREFIX + "/prepare",
            data={"csrf": field(page.text, "csrf"), "device_id": "1", "action": "block"},
        )
        assert prepared.status_code == 200
        assert "IP : 192.168.1.20" in prepared.text
        assert "MAC : 02:00:00:00:00:20" in prepared.text
        assert "Action : Bloquer" in prepared.text
        assert calls == []
        data = {
            "csrf": field(prepared.text, "csrf"),
            "token": field(prepared.text, "token"),
            "confirm": "yes",
        }
        done = client.post(PREFIX + "/confirm", data=data)
        assert done.status_code == 200
        assert len(calls) == 1
        for stage in [page, prepared, done]:
            assert 'aria-label="Navigation principale"' in stage.text
            assert 'href="/logout"' in stage.text
            assert f'href="{PREFIX}"' in stage.text
            assert "Retour aux routeurs" in stage.text
            assert session not in stage.text
            assert CREDENTIAL not in stage.text
            for name, value in SECURITY_HEADERS.items():
                assert stage.headers[name] == value
        assert 'name="token"' not in done.text
        assert client.post(PREFIX + "/confirm", data=data).status_code == 409
        assert len(calls) == 1


def test_confirmation_template_escapes_text_and_hidden_fields() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined, autoescape=True
    )
    payload = '<script>alert("synthetic")</script>'
    text = env.get_template("livebox_confirmation.html").render(
        stage="confirm",
        prefix=PREFIX,
        device_id=1,
        address=payload,
        mac=payload,
        action=payload,
        token=payload,
        csrf=payload,
    )
    assert payload not in text
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
