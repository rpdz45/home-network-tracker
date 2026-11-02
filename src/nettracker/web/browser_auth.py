"""Browser login/logout routes; explicitly installed by the application."""

import hmac
import secrets
from collections.abc import Callable
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from nettracker.web.sessions import SessionCapacityError, SessionStore

COOKIE_NAME = "nettracker_session"
PREAUTH_COOKIE = "nettracker_login_csrf"
MAX_BYTES = 4096
MAX_AGE = 8 * 3600


def _matches(expected: str, supplied: str | None) -> bool:
    return bool(supplied) and secrets.compare_digest(expected.encode(), supplied.encode())


async def _form(request: Request, fields: set[str]) -> dict[str, str]:
    origin = request.headers.get("origin")
    if (origin is not None and origin != str(request.base_url).rstrip("/")) or (
        request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(403, "Origine refusée")
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formulaire attendu")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Requête trop volumineuse")
        body.extend(chunk)
    try:
        values = parse_qs(
            body.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=len(fields),
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Formulaire invalide") from None
    if set(values) != fields or any(len(items) != 1 for items in values.values()):
        raise HTTPException(422, "Champs invalides")
    return {key: items[0] for key, items in values.items()}


def install_browser_auth(
    app: FastAPI,
    credential: str | None,
    *,
    sessions: SessionStore | None = None,
) -> Callable[[Request], None]:
    """Install once, instead of legacy login routes; return the auth dependency.

    No dashboard imports this yet. Use one process. HTTPS termination and trusted
    forwarded headers are deployment responsibilities. Bearer does not create a
    browser session. The supplied store must use the default eight-hour TTL.
    """
    store = sessions if sessions is not None else SessionStore()
    key = secrets.token_bytes(32)

    def signature(purpose: str, value: str) -> str:
        return hmac.digest(key, f"{purpose}:{value}".encode(), "sha256").hex()

    def cookie(response: Response, request: Request, name: str, value: str, age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=age,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )

    def page(content: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(
            '<!doctype html><html lang="fr"><meta charset="utf-8">'
            "<title>Session · Home Network Tracker</title><main>" + content + "</main></html>",
            status_code=status,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    def browser_session(request: Request) -> str:
        session = store.resolve(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise HTTPException(303, headers={"Location": "/login"})
        return session

    def require_auth(request: Request) -> None:
        if not credential:
            return
        header = request.headers.get("authorization")
        if header is None:
            request.state.browser_session_id = browser_session(request)
            return
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not _matches(credential, supplied.strip()):
            raise HTTPException(401, "unauthorized")

    @app.get("/login")
    def login_page(request: Request) -> Response:
        if not credential:
            return RedirectResponse("/", 303)
        nonce = secrets.token_urlsafe(32)
        csrf = signature("login", nonce)
        response = page(
            '<h1>Connexion</h1><form method="post" action="/login">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            '<label>Jeton <input type="password" name="token" '
            'autocomplete="current-password" required></label>'
            '<button type="submit">Se connecter</button></form>'
        )
        cookie(response, request, PREAUTH_COOKIE, nonce, 600)
        return response

    @app.post("/login")
    async def login(request: Request) -> Response:
        if not credential:
            return RedirectResponse("/", 303)
        form = await _form(request, {"token", "csrf"})
        nonce = request.cookies.get(PREAUTH_COOKIE, "")
        if len(nonce) != 43 or not _matches(signature("login", nonce), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        if not _matches(credential, form["token"]):
            return page('<p>Jeton invalide.</p><a href="/login">Réessayer</a>', 401)
        try:
            session = store.issue()
        except SessionCapacityError:
            raise HTTPException(503, "Connexion temporairement indisponible") from None
        store.revoke(request.cookies.get(COOKIE_NAME))
        response = RedirectResponse("/", 303, headers={"Cache-Control": "no-store"})
        cookie(response, request, COOKIE_NAME, session, MAX_AGE)
        response.delete_cookie(PREAUTH_COOKIE, path="/")
        return response

    @app.get("/logout")
    def logout_page(request: Request) -> Response:
        session = browser_session(request)
        csrf = escape(signature("logout", session), quote=True)
        return page(
            '<h1>Déconnexion</h1><form method="post" action="/logout">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            '<button type="submit">Confirmer la déconnexion</button></form>'
        )

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        session = browser_session(request)
        form = await _form(request, {"csrf"})
        if not _matches(signature("logout", session), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        store.revoke(session)
        response = RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    return require_auth
