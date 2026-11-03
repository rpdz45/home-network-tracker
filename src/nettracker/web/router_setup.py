"""Browser-configured, explicit router reads; no persistence or access-rule writes."""

import hmac
import secrets
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.routers import bbox, bbox_session, livebox5
from nettracker.web.browser_auth import _form, _matches

PREFIX = "/routers/setup"


def _text(value: object, secret: str) -> str:
    if not isinstance(value, str) or not value:
        return "Non renseigné"
    return value.replace(secret, "[masqué]")[:128]


def install_router_setup(
    protected: APIRouter, settings: Settings, templates: Jinja2Templates
) -> None:
    """Require the parent's browser authentication before accepting a target.

    A saved environment activation is not needed: each POST grants one explicit
    read within the server-owned subnets. No credentials or profiles are saved.
    """
    key = secrets.token_bytes(32)
    lock = Lock()
    attempts: dict[str, float] = {}

    def session(request: Request) -> str:
        value = getattr(request.state, "browser_session_id", None)
        if (
            settings.api.token is None
            or not settings.api.token.get_secret_value()
            or request.headers.get("authorization") is not None
            or not isinstance(value, str)
            or not value
        ):
            raise HTTPException(403, "Connectez-vous au dashboard avec une session navigateur")
        return value

    def csrf(value: str) -> str:
        return hmac.digest(key, ("router-setup:" + value).encode(), "sha256").hex()

    def page(
        request: Request,
        session_id: str,
        *,
        kind: str = "livebox5",
        address: str = "",
        model: str = "",
        allow_http: bool = False,
        rows: list[dict[str, str]] | None = None,
        error: bool = False,
        status: int = 200,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "router_setup.html",
            {
                "csrf": csrf(session_id),
                "kind": kind,
                "address": address,
                "model": model,
                "allow_http": allow_http,
                "rows": rows if rows is not None else [],
                "loaded": rows is not None,
                "error": error,
                "subnets": [str(network) for network in settings.allowed_subnets],
            },
            status_code=status,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @protected.get(PREFIX)
    def setup(request: Request) -> HTMLResponse:
        return page(request, session(request))

    @protected.post(PREFIX + "/read")
    async def read(request: Request) -> HTMLResponse:
        session_id = session(request)
        form = await _form(
            request, {"csrf", "kind", "address", "model", "allow_http", "password", "confirm"}
        )
        if not _matches(csrf(session_id), form["csrf"]):
            raise HTTPException(403, "Protection CSRF invalide")
        kind = form["kind"]
        if (
            kind not in {"livebox5", "bbox"}
            or form["confirm"] != "yes"
            or form["allow_http"] not in {"no", "yes"}
            or not 1 <= len(form["password"]) <= 256
            or not 1 <= len(form["address"]) <= 256
            or len(form["model"]) > 128
            or (kind == "bbox" and not form["model"].strip())
        ):
            raise HTTPException(422, "Box, adresse, modèle ou confirmation invalide")
        allow_http = form["allow_http"] == "yes"
        model = form["model"].strip() if kind == "bbox" else ""
        try:
            if kind == "livebox5":
                address = livebox5._endpoint(
                    form["address"], settings.allowed_subnets, allow_http
                ).removesuffix("/ws")
            else:
                address = bbox._origin(form["address"], settings.allowed_subnets, allow_http)
        except (livebox5.LiveboxError, bbox.BboxError):
            raise HTTPException(
                422,
                "Adresse refusée : IPv4 privée autorisée et HTTPS, ou HTTP accepté explicitement",
            ) from None
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "Une lecture de box est déjà en cours")
        try:
            cooldown = 60 if kind == "livebox5" else 900
            previous = attempts.get(kind)
            if previous is not None and monotonic() - previous < cooldown:
                raise HTTPException(
                    429, f"Attendre {cooldown} secondes entre lectures de cette box"
                )
            attempts[kind] = monotonic()
            password = SecretStr(form["password"])
            rows: list[dict[str, str]] = []
            try:
                if kind == "livebox5":
                    snapshot = await run_in_threadpool(
                        livebox5.read_snapshot,
                        address,
                        settings.allowed_subnets,
                        password,
                        enabled=True,
                        allow_http=allow_http,
                    )
                    for device in snapshot.devices:
                        active = device.get("Active")
                        state = "Actif selon la box" if active is True else "État non renseigné"
                        if active is False:
                            state = "Inactif selon la box"
                        rows.append(
                            {
                                "name": _text(device.get("Name"), form["password"]),
                                "ip": _text(device.get("IPAddress"), form["password"]),
                                "mac": _text(device.get("PhysAddress"), form["password"]),
                                "state": state,
                            }
                        )
                else:
                    bbox_snapshot = await run_in_threadpool(
                        bbox_session.read_authenticated_snapshot,
                        address,
                        settings.allowed_subnets,
                        password,
                        model,
                        enabled=True,
                        confirmed=True,
                        allow_http=allow_http,
                    )
                    for host in bbox_snapshot.hosts:
                        state = (
                            "Actif selon la box" if host.active is True else "État non renseigné"
                        )
                        if host.active is False:
                            state = "Inactif selon la box"
                        rows.append(
                            {
                                "name": _text(host.name, form["password"]),
                                "ip": _text(host.address, form["password"]),
                                "mac": _text(host.mac, form["password"]),
                                "state": state,
                            }
                        )
            except (livebox5.LiveboxError, bbox.BboxError):
                return page(
                    request,
                    session_id,
                    kind=kind,
                    address=address,
                    model=model,
                    allow_http=allow_http,
                    error=True,
                    status=503,
                )
            finally:
                attempts[kind] = monotonic()
            return page(
                request,
                session_id,
                kind=kind,
                address=address,
                model=model,
                allow_http=allow_http,
                rows=rows,
            )
        finally:
            lock.release()
