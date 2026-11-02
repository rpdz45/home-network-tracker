"""Read-only control availability; TestClient never contacts a router."""

from html.parser import HTMLParser
from ipaddress import IPv4Network
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nettracker.config import ApiSettings, Settings
from nettracker.web.app import create_app


class Controls(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "button" and "aria-describedby" in values:
            self.buttons.append(values)


def settings(path: Path, authenticated: bool = False) -> Settings:
    return Settings(
        allowed_subnets=[IPv4Network("192.168.1.0/24")],
        database_path=path,
        api=ApiSettings(token=SecretStr("synthetic-dashboard-token") if authenticated else None),
    )


def test_status_without_database_or_outgoing_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail("page rendering must not use an outgoing HTTP transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    path = tmp_path / "absent.db"
    with TestClient(create_app(settings(path))) as client:
        response = client.get("/routers")
    assert response.status_code == 200
    assert not path.exists()
    assert "Service et adaptateur développés" in response.text
    assert "adaptateur HTTP d'écriture non fourni" in response.text
    assert "Aucune simulation interactive" in response.text
    assert response.headers["cache-control"] == "no-store"
    parser = Controls()
    parser.feed(response.text)
    assert len(parser.buttons) == 4
    assert all("disabled" in button and button["type"] == "button" for button in parser.buttons)


def test_status_respects_configured_authentication(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path / "absent.db", True))) as client:
        denied = client.get("/routers", follow_redirects=False)
        assert denied.status_code == 303
        assert denied.headers["location"] == "/login"
        response = client.get(
            "/routers", headers={"Authorization": "Bearer synthetic-dashboard-token"}
        )
    assert response.status_code == 200
    assert "router-control-status" in response.text


@pytest.mark.parametrize("router", ["bbox", "livebox"])
def test_no_control_write_route(tmp_path: Path, router: str) -> None:
    with TestClient(create_app(settings(tmp_path / "absent.db"))) as client:
        response = client.post(f"/routers/{router}/control", data={"blocked": "true"})
    assert response.status_code in {404, 405}
