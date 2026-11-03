"""Navigation is presentation only; real route guards remain authoritative."""

from ipaddress import IPv4Address, IPv4Network
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nettracker.config import Settings
from nettracker.routers.control import AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.app import TEMPLATES_DIR, create_app


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("browser_session", [False, True])
def test_navigation_requires_enabled_app_and_browser_session(
    enabled: bool, browser_session: bool
) -> None:
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
        {"allowed_subnets": ["192.168.1.0/24"], "api": {"token": "synthetic-nav-credential"}}
    )
    app = create_app(settings, livebox_guard=guard, livebox_control_enabled=enabled)
    state = SimpleNamespace()
    if browser_session:
        state.browser_session_id = "synthetic-nav-session"
    request = SimpleNamespace(app=app, state=state)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined, autoescape=True
    )
    text = env.get_template("base.html").render(request=request)
    assert ('href="/routers/livebox/control"' in text) == (enabled and browser_session)
    assert "synthetic-nav-session" not in text
    assert "synthetic-nav-credential" not in text
    assert app.state.livebox_control_navigation is enabled
    assert calls == []


@pytest.mark.parametrize(
    "request_context",
    [
        SimpleNamespace(),
        SimpleNamespace(state=SimpleNamespace()),
        SimpleNamespace(state=SimpleNamespace(browser_session_id="synthetic-session")),
        SimpleNamespace(
            state=SimpleNamespace(browser_session_id="synthetic-session"),
            app=SimpleNamespace(state=SimpleNamespace()),
        ),
    ],
)
def test_incomplete_context_hides_livebox_link(request_context: object) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined, autoescape=True
    )
    text = env.get_template("base.html").render(request=request_context)
    assert 'href="/routers/livebox/control"' not in text
