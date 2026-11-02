"""HTTP tests on an isolated app, not dashboard integration tests."""

import re

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nettracker.web.browser_auth import COOKIE_NAME, install_browser_auth
from nettracker.web.sessions import SessionStore

CREDENTIAL = "synthetic-test-credential"


def application(store: SessionStore | None = None) -> FastAPI:
    app = FastAPI()
    auth = install_browser_auth(app, CREDENTIAL, sessions=store)

    @app.get("/private", dependencies=[Depends(auth)])
    def private() -> dict[str, bool]:
        return {"ok": True}

    return app


def csrf(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match is not None
    return match[1]


def login(client: TestClient) -> str:
    response = client.post(
        "/login",
        data={"csrf": csrf(client, "/login"), "token": CREDENTIAL},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    token = client.cookies[COOKIE_NAME]
    assert token != CREDENTIAL
    return token


def test_distinct_sessions_and_isolated_logout() -> None:
    app = application()
    with TestClient(app) as first, TestClient(app) as second:
        old = login(first)
        assert login(second) != old
        confirmation = csrf(first, "/logout")
        assert first.get("/private").status_code == 200
        denied = second.post("/logout", data={"csrf": confirmation})
        assert denied.status_code == 403
        assert (
            first.post(
                "/logout",
                data={"csrf": confirmation},
                follow_redirects=False,
            ).status_code
            == 303
        )
        first.cookies.set(COOKIE_NAME, old)
        assert first.get("/private", follow_redirects=False).status_code == 303
        assert second.get("/private").status_code == 200


def test_legacy_cookie_rejected_and_bearer_preserved() -> None:
    with TestClient(application()) as client:
        client.cookies.set(COOKIE_NAME, CREDENTIAL)
        assert client.get("/private", follow_redirects=False).status_code == 303
        assert (
            client.get(
                "/private",
                headers={"Authorization": f"Bearer {CREDENTIAL}"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/private",
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )


def test_expiration_is_enforced_server_side() -> None:
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    with TestClient(application(store)) as client:
        login(client)
        now[0] = 8 * 3600
        assert client.get("/private", follow_redirects=False).status_code == 303


def test_failed_login_does_not_allocate_session() -> None:
    store = SessionStore(capacity=1)
    with TestClient(application(store)) as client:
        token = csrf(client, "/login")
        assert (
            client.post(
                "/login",
                data={"csrf": token, "token": "wrong"},
            ).status_code
            == 401
        )
        assert COOKIE_NAME not in client.cookies
        assert (
            client.post(
                "/login",
                data={"csrf": "wrong", "token": CREDENTIAL},
            ).status_code
            == 403
        )
        login(client)


def test_cross_site_and_invalid_forms_are_refused() -> None:
    with TestClient(application()) as client:
        data = {"csrf": csrf(client, "/login"), "token": CREDENTIAL}
        assert (
            client.post(
                "/login",
                data=data,
                headers={"Origin": "https://invalid.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/login",
                data=data,
                headers={"Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        assert client.post("/login", json=data).status_code == 415
        assert client.post("/login", data={"token": CREDENTIAL}).status_code == 422
        assert (
            client.post(
                "/login",
                content="x=" + "a" * 5000,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).status_code
            == 413
        )


def test_https_cookie_is_secure() -> None:
    with TestClient(application(), base_url="https://testserver") as client:
        response = client.get("/login")
        assert "Secure" in response.headers["set-cookie"]
        response = client.post(
            "/login",
            data={"csrf": csrf(client, "/login"), "token": CREDENTIAL},
            follow_redirects=False,
        )
        assert "Secure" in response.headers["set-cookie"]
