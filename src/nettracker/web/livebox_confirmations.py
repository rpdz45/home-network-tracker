"""Explicitly installed HTTP confirmation flow; no production adapter is constructed."""

import hmac
import secrets
from pathlib import Path
from typing import TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from nettracker.routers.control import AccessControlError, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.browser_auth import COOKIE_NAME, _form, _matches
from nettracker.web.livebox_execution import confirm_livebox_result
from nettracker.web.session_control import SessionBoundControl
from nettracker.web.sessions import SessionStore

Result = TypeVar("Result")
PREFIX = "/routers/livebox/control"
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
}


def install_livebox_confirmation_routes(
    app: FastAPI,
    sessions: SessionStore,
    guard: ControlGuards[Result],
    *,
    enabled: bool = False,
) -> None:
    """Install once with the authentication store and a server-owned Livebox guard.

    Callers retain adapter validation and read-back responsibility. This module
    does not enable itself, choose a router, load credentials or open a database.
    A missing or inconsistent executor result is refused, not shown as success.
    """
    control = SessionBoundControl(sessions, guard, enabled=enabled)
    key = secrets.token_bytes(32)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def session_cookie(request: Request) -> str:
        if enabled is not True:
            raise HTTPException(403, "Contrôle web non activé")
        if request.headers.get("authorization") is not None:
            raise HTTPException(403, "Session navigateur requise, sans en-tête Authorization")
        session = sessions.resolve(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise HTTPException(403, "Session navigateur absente ou expirée")
        request.state.browser_session_id = session
        return session

    def csrf(cookie: str, purpose: str) -> str:
        return hmac.digest(key, f"{cookie}:{purpose}".encode(), "sha256").hex()

    def page(request: Request, stage: str, context: dict[str, object]) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "livebox_confirmation.html",
            {**context, "stage": stage, "prefix": PREFIX},
            headers=HEADERS,
        )

    @app.get(PREFIX)
    def control_form(request: Request) -> HTMLResponse:
        cookie = session_cookie(request)
        return page(request, "prepare", {"csrf": csrf(cookie, "prepare")})

    @app.post(PREFIX + "/prepare")
    async def prepare(request: Request) -> HTMLResponse:
        cookie = session_cookie(request)
        form = await _form(request, {"csrf", "device_id", "action"})
        if not _matches(csrf(cookie, "prepare"), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        raw_id = form["device_id"]
        if not raw_id.isascii() or not raw_id.isdecimal() or len(raw_id) > 10:
            raise HTTPException(422, "Identifiant invalide")
        device_id = int(raw_id)
        if device_id < 1 or str(device_id) != raw_id or form["action"] not in {"block", "release"}:
            raise HTTPException(422, "Cible ou action invalide")
        try:
            pending = await run_in_threadpool(
                control.prepare, device_id, form["action"] == "block", cookie=cookie
            )
        except AccessControlError:
            raise HTTPException(409, "Préparation refusée ; aucune commande exécutée") from None
        if pending.request.router != RouterKind.LIVEBOX5:
            raise HTTPException(409, "Cible Livebox requise")
        return page(
            request,
            "confirm",
            {
                "device_id": pending.device_id,
                "address": str(pending.request.address),
                "mac": pending.request.mac,
                "action": "Bloquer" if pending.request.blocked else "Retirer le forçage",
                "token": pending.token,
                "csrf": csrf(cookie, "confirm:" + pending.token),
            },
        )

    @app.post(PREFIX + "/confirm")
    async def confirm(request: Request) -> HTMLResponse:
        cookie = session_cookie(request)
        form = await _form(request, {"csrf", "token", "confirm"})
        if not _matches(csrf(cookie, "confirm:" + form["token"]), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        if form["confirm"] != "yes":
            raise HTTPException(422, "Confirmation explicite requise")
        result = await run_in_threadpool(
            confirm_livebox_result, control, form["token"], cookie=cookie
        )
        return page(request, "done", {"result": result})
