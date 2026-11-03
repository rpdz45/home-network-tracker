"""Explicitly installed HTTP confirmation flow; no production adapter is constructed."""

import hmac
import secrets
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from nettracker.routers.control import AccessControlError, RouterKind
from nettracker.routers.control_guards import ControlGuards
from nettracker.web.browser_auth import COOKIE_NAME, _form, _matches
from nettracker.web.session_control import SessionBoundControl
from nettracker.web.sessions import SessionStore

PREFIX = "/routers/livebox/control"
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


def install_livebox_confirmation_routes(
    app: FastAPI,
    sessions: SessionStore,
    guard: ControlGuards[None],
    *,
    enabled: bool = False,
) -> None:
    """Install once with the authentication store and a server-owned Livebox guard.

    Callers retain adapter validation and read-back responsibility. This module
    does not enable itself, choose a router, load credentials or open a database.
    """
    control = SessionBoundControl(sessions, guard, enabled=enabled)
    key = secrets.token_bytes(32)

    def session_cookie(request: Request) -> str:
        if enabled is not True:
            raise HTTPException(403, "Contrôle web non activé")
        if request.headers.get("authorization") is not None:
            raise HTTPException(403, "Session navigateur requise, sans en-tête Authorization")
        session = sessions.resolve(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise HTTPException(403, "Session navigateur absente ou expirée")
        return session

    def csrf(cookie: str, purpose: str) -> str:
        return hmac.digest(key, f"{cookie}:{purpose}".encode(), "sha256").hex()

    def page(content: str) -> HTMLResponse:
        return HTMLResponse(
            '<!doctype html><html lang="fr"><meta charset="utf-8">'
            "<title>Confirmation Livebox</title><main>" + content + "</main></html>",
            headers=HEADERS,
        )

    @app.get(PREFIX)
    def control_form(request: Request) -> HTMLResponse:
        cookie = session_cookie(request)
        token = csrf(cookie, "prepare")
        return page(
            '<h1>Préparer une commande Livebox</h1>'
            '<p>Aucune commande au simple affichage. Compatibilité matérielle non certifiée.</p>'
            f'<form method="post" action="{PREFIX}/prepare">'
            f'<input type="hidden" name="csrf" value="{token}">'
            "<label>Identifiant local de l'appareil "
            '<input name="device_id" type="number" min="1" required></label>'
            '<label>Action <select name="action">'
            '<option value="block">Bloquer</option>'
            '<option value="release">Retirer le forçage</option></select></label>'
            '<button type="submit">Vérifier la cible</button></form>'
        )

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
        action = "Bloquer" if pending.request.blocked else "Retirer le forçage"
        token = escape(pending.token, quote=True)
        proof = csrf(cookie, "confirm:" + pending.token)
        return page(
            '<h1>Confirmer la commande Livebox</h1>'
            f'<p>Appareil local : {pending.device_id}</p>'
            f'<p>IP : {escape(str(pending.request.address))}</p>'
            f'<p>MAC : {escape(pending.request.mac)}</p><p>Action : {action}</p>'
            "<p>Retirer le forçage ne garantit pas l'accès si le calendrier l'interdit.</p>"
            '<p>Confirmation temporaire, à usage unique. La cible sera revérifiée.</p>'
            f'<form method="post" action="{PREFIX}/confirm">'
            f'<input type="hidden" name="csrf" value="{proof}">'
            f'<input type="hidden" name="token" value="{token}">'
            '<label><input type="checkbox" name="confirm" value="yes" required>'
            ' Je confirme cette cible et cette action.</label>'
            '<button type="submit">Confirmer</button></form>'
        )

    @app.post(PREFIX + "/confirm")
    async def confirm(request: Request) -> HTMLResponse:
        cookie = session_cookie(request)
        form = await _form(request, {"csrf", "token", "confirm"})
        if not _matches(csrf(cookie, "confirm:" + form["token"]), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        if form["confirm"] != "yes":
            raise HTTPException(422, "Confirmation explicite requise")
        try:
            await run_in_threadpool(control.confirm, form["token"], cookie=cookie)
        except AccessControlError:
            raise HTTPException(
                409, "Confirmation refusée ou résultat incertain ; ne pas relancer automatiquement"
            ) from None
        return page(
            "<h1>Traitement terminé</h1><p>L'exécuteur configuré a terminé sans erreur.</p>"
            "<p>Ce message seul ne prouve ni l'accès Internet ni la compatibilité matérielle.</p>"
        )
