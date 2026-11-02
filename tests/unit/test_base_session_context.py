"""Base navigation accepts optional HTTP context, including StrictUndefined renders."""

from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nettracker.web.app import TEMPLATES_DIR


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"request": SimpleNamespace()},
        {"request": SimpleNamespace(state=SimpleNamespace())},
    ],
)
def test_missing_session_context_hides_logout(context: dict[str, object]) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined, autoescape=True
    )
    text = env.get_template("base.html").render(**context)
    assert 'href="/logout"' not in text


def test_session_context_shows_link_without_rendering_secret() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined, autoescape=True
    )
    request = SimpleNamespace(state=SimpleNamespace(browser_session_id="synthetic-session-secret"))
    text = env.get_template("base.html").render(request=request)
    assert 'href="/logout"' in text
    assert "synthetic-session-secret" not in text
