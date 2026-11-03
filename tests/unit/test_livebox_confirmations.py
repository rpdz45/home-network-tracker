"""Isolated HTTP flow sharing actual browser sessions; synthetic execution only."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nettracker.routers.control import AccessControlError, AccessRequest, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.routers.livebox5 import LiveboxError
from nettracker.routers.livebox5_access import ScheduleState
from nettracker.routers.livebox5_control import ControlResult
from nettracker.web.browser_auth import install_browser_auth
from nettracker.web.livebox_confirmations import PREFIX, install_livebox_confirmation_routes
from nettracker.web.livebox_results import FAILURE_DETAIL
from nettracker.web.sessions import SessionStore

CREDENTIAL = "synthetic-http-confirmation-credential"


@dataclass
class Harness:
    app: FastAPI
    calls: list[AccessRequest]
    now: list[float]


def application(
    *,
    enabled: bool = True,
    session_ttl: float = 8 * 3600,
    execute: Callable[[AccessRequest], object] | None = None,
) -> Harness:
    now = [0.0]
    sessions = SessionStore(ttl=session_ttl, clock=lambda: now[0])
    calls: list[AccessRequest] = []

    def record(request: AccessRequest) -> object:
        calls.append(request)
        if execute is not None:
            return execute(request)
        return ControlResult(
            True, ScheduleState("Disable" if request.blocked else "", "Disable")
        )

    guard = ControlGuards[object](
        lambda device, blocked: AccessRequest(
            RouterKind.LIVEBOX5, IPv4Address("192.168.1.20"), "02:00:00:00:00:20", blocked
        ),
        record,
        [IPv4Network("192.168.1.0/24")],
        ["02:00:00:00:00:01"],
        enabled=True,
        clock=lambda: now[0],
    )
    app = FastAPI()
    install_browser_auth(app, CREDENTIAL, sessions=sessions)
    install_livebox_confirmation_routes(app, sessions, guard, enabled=enabled)
    return Harness(app, calls, now)


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


def prepare(client: TestClient, *, blocked: bool = True) -> dict[str, str]:
    page = client.get(PREFIX)
    assert page.status_code == 200
    response = client.post(
        PREFIX + "/prepare",
        data={
            "csrf": field(page.text, "csrf"),
            "device_id": "1",
            "action": "block" if blocked else "release",
        },
    )
    assert response.status_code == 200
    assert "192.168.1.20" in response.text
    assert "02:00:00:00:00:20" in response.text
    assert ("Action : Bloquer" if blocked else "Action : Retirer le forçage") in response.text
    return {
        "csrf": field(response.text, "csrf"),
        "token": field(response.text, "token"),
        "confirm": "yes",
    }


def test_prepare_is_inert_confirm_once_and_replay_refused() -> None:
    harness = application()
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        assert harness.calls == []
        response = client.post(PREFIX + "/confirm", data=data)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "Résultat du contrôle Livebox" in response.text
        assert "Modification effectuée" in response.text
        assert len(harness.calls) == 1
        assert client.post(PREFIX + "/confirm", data=data).status_code == 409
        assert len(harness.calls) == 1


def test_other_browser_cannot_confirm() -> None:
    harness = application()
    with TestClient(harness.app) as first, TestClient(harness.app) as second:
        login(first)
        login(second)
        data = prepare(first)
        assert second.post(PREFIX + "/confirm", data=data).status_code == 403
        assert harness.calls == []
        assert first.post(PREFIX + "/confirm", data=data).status_code == 200
        assert len(harness.calls) == 1


def test_logout_and_new_login_do_not_restore_confirmation() -> None:
    harness = application()
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        page = client.get("/logout")
        response = client.post(
            "/logout", data={"csrf": field(page.text, "csrf")}, follow_redirects=False
        )
        assert response.status_code == 303
        assert client.post(PREFIX + "/confirm", data=data).status_code == 403
        login(client)
        assert client.post(PREFIX + "/confirm", data=data).status_code == 403
        assert harness.calls == []


def test_session_expiry_and_confirmation_expiry() -> None:
    for session_ttl, elapsed, expected in [(10, 10, 403), (8 * 3600, 60, 409)]:
        harness = application(session_ttl=session_ttl)
        with TestClient(harness.app) as client:
            login(client)
            data = prepare(client)
            harness.now[0] = elapsed
            assert client.post(PREFIX + "/confirm", data=data).status_code == expected
            assert harness.calls == []


def test_explicit_confirmation_csrf_and_origin_are_required() -> None:
    harness = application()
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        denied = client.post(PREFIX + "/confirm", data={**data, "confirm": "no"})
        assert denied.status_code == 422
        denied = client.post(PREFIX + "/confirm", data={**data, "csrf": "wrong"})
        assert denied.status_code == 403
        denied = client.post(
            PREFIX + "/confirm", data=data, headers={"Origin": "https://invalid.example"}
        )
        assert denied.status_code == 403
        assert harness.calls == []


def test_bearer_and_disabled_flow_are_refused() -> None:
    harness = application()
    with TestClient(harness.app) as client:
        response = client.get(PREFIX, headers={"Authorization": f"Bearer {CREDENTIAL}"})
        assert response.status_code == 403
        assert client.get(PREFIX).status_code == 403
    disabled = application(enabled=False)
    with TestClient(disabled.app) as client:
        login(client)
        assert client.get(PREFIX).status_code == 403
        assert client.post(PREFIX + "/prepare", data={}).status_code == 403
        assert client.post(PREFIX + "/confirm", data={}).status_code == 403
    assert harness.calls == disabled.calls == []


@pytest.mark.parametrize("blocked", [True, False])
@pytest.mark.parametrize("changed", [True, False])
def test_http_renders_result_for_server_confirmed_action(blocked: bool, changed: bool) -> None:
    harness = application(
        execute=lambda request: ControlResult(
            changed, ScheduleState("Disable" if request.blocked else "", "Disable")
        )
    )
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client, blocked=blocked)
        response = client.post(PREFIX + "/confirm", data=data)
        assert response.status_code == 200
        assert (
            "Modification effectuée" if changed else "Etat déjà conforme, sans modification"
        ) in response.text
        assert ("Forçage de blocage présent" if blocked else "Aucun forçage") in response.text
        assert "accès désactivé" in response.text
        assert "ne prouve pas" in response.text
        assert "Traitement terminé" not in response.text
        assert 'name="token"' not in response.text
        assert len(harness.calls) == 1
        assert harness.calls[0].blocked is blocked
        assert client.post(PREFIX + "/confirm", data=data).status_code == 409
        assert len(harness.calls) == 1


@pytest.mark.parametrize("error_type", [AccessControlError, LiveboxError])
def test_http_known_failure_is_masked_and_cannot_replay(error_type: type[Exception]) -> None:
    def fail(request: AccessRequest) -> object:
        raise error_type("synthetic-private-detail")

    harness = application(execute=fail)
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        for _ in range(2):
            response = client.post(PREFIX + "/confirm", data=data)
            assert response.status_code == 409
            assert response.json() == {"detail": FAILURE_DETAIL}
            assert "synthetic-private-detail" not in response.text
        assert len(harness.calls) == 1


@pytest.mark.parametrize("result", [None, ControlResult(True, ScheduleState("", "Enable"))])
def test_http_invalid_result_is_not_success_and_cannot_replay(result: object) -> None:
    harness = application(execute=lambda request: result)
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        for _ in range(2):
            response = client.post(PREFIX + "/confirm", data=data)
            assert response.status_code == 409
            assert response.json() == {"detail": FAILURE_DETAIL}
        assert len(harness.calls) == 1


def test_http_cannot_supply_a_different_confirmed_action() -> None:
    harness = application()
    with TestClient(harness.app) as client:
        login(client)
        data = prepare(client)
        assert client.post(PREFIX + "/confirm", data={**data, "action": "release"}).status_code == 422
        assert harness.calls == []
        assert client.post(PREFIX + "/confirm", data=data).status_code == 200
        assert len(harness.calls) == 1
        assert harness.calls[0].blocked is True
