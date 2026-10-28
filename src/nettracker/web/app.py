"""Local dashboard with explicit device edits and router diagnostics."""

import hmac
import logging
import secrets
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.db import Repository, connect
from nettracker.db.device_edits import DEVICE_TYPES, mark_known, update_identity
from nettracker.db.health import CollectorHealth, collector_health
from nettracker.errors import NetTrackerError
from nettracker.web import queries
from nettracker.web.formatting import paris_datetime
from nettracker.web.router_dashboard import install_router_dashboard
from nettracker.web.timeseries import load_series

logger = logging.getLogger(__name__)

COOKIE_NAME = "nettracker_session"
COOKIE_MAX_AGE = 8 * 3600
MAX_LOGIN_BYTES = 4096
TEMPLATES_DIR = Path(__file__).parent / "templates"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _expected_credential(settings: Settings) -> str | None:
    configured = settings.api.token
    if configured is None:
        return None
    return configured.get_secret_value() or None


def _matches(expected: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return secrets.compare_digest(supplied.encode(), expected.encode())


def _health_view(health: CollectorHealth) -> tuple[str, str]:
    if health.last_success_at is None:
        return "aucun scan réussi", "warn"
    if health.stale:
        return "périmé", "bad"
    return "OK", "ok"


async def _read_limited(request: Request, limit: int) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            return None
        body.extend(chunk)
    return bytes(body)


def _save_device(settings: Settings, device_id: int, form: dict[str, list[str]]) -> None:
    check = queries.open_readonly(settings.database_path)
    check.close()
    conn = connect(settings.database_path)
    try:
        with Repository(conn).transaction():
            update_identity(
                conn, device_id, alias=form["alias"][0], device_type=form["device_type"][0]
            )
            if form.get("mark_known") == ["yes"]:
                mark_known(conn, device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Appareil introuvable") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Modification invalide ou appareil non modifiable"
        ) from exc
    finally:
        conn.close()


def create_app(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Build the dashboard; edits always require a configured credential, even on loopback."""
    expected = _expected_credential(settings)
    csrf_key = secrets.token_bytes(32)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["paris_datetime"] = paris_datetime
    app = FastAPI(title="Home Network Tracker", docs_url=None, redoc_url=None, openapi_url=None)

    def csrf_for(device_id: int) -> str:
        return hmac.digest(csrf_key, str(device_id).encode(), "sha256").hex()

    @contextmanager
    def database() -> Iterator[sqlite3.Connection]:
        conn = queries.open_readonly(settings.database_path)
        try:
            yield conn
        finally:
            conn.close()

    def require_auth(request: Request) -> None:
        if expected is None:
            return
        header = request.headers.get("authorization")
        if header is None:
            if _matches(expected, request.cookies.get(COOKIE_NAME)):
                return
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() == "bearer" and _matches(expected, supplied.strip()):
            return
        raise HTTPException(status_code=401, detail="unauthorized")

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(NetTrackerError)
    async def database_unavailable(request: Request, exc: Exception) -> Response:
        logger.warning("dashboard request failed: %s", type(exc).__name__)
        return PlainTextResponse("Service indisponible : base de données non prête.", 503)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Response:
        if expected is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": False})

    @app.post("/login")
    async def login(request: Request) -> Response:
        if expected is None:
            return RedirectResponse("/", status_code=303)
        body = await _read_limited(request, MAX_LOGIN_BYTES)
        if body is None:
            return PlainTextResponse("Requête trop volumineuse.", status_code=413)
        form = parse_qs(body.decode("utf-8", errors="replace"))
        if not _matches(expected, form.get("token", [""])[0]):
            return templates.TemplateResponse(
                request, "login.html", {"error": True}, status_code=401
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME, expected, max_age=COOKIE_MAX_AGE, httponly=True, samesite="strict"
        )
        return response

    protected = APIRouter(dependencies=[Depends(require_auth)])

    @protected.get("/", response_class=HTMLResponse)
    def devices_page(request: Request) -> Response:
        threshold = settings.health.stale_after_minutes * 60
        with database() as conn:
            devices = queries.list_devices(conn)
            health = collector_health(conn, clock(), threshold)
        label, css = _health_view(health)
        context = {
            "devices": devices,
            "health": health,
            "health_label": label,
            "health_class": css,
            "monitoring_enabled": settings.monitor.enabled,
        }
        return templates.TemplateResponse(request, "devices.html", context)

    @protected.get("/devices/{device_id}", response_class=HTMLResponse)
    def device_page(
        request: Request, device_id: int, window: Literal["24h", "7d"] = "24h"
    ) -> Response:
        with database() as conn:
            device = queries.get_device(conn, device_id)
            if device is None:
                raise HTTPException(status_code=404, detail="Appareil introuvable")
            context = {
                "device": device,
                "sightings": queries.device_sightings(conn, device_id),
                "events": queries.device_events(conn, device_id),
                "can_edit": expected is not None and device["merged_into"] is None,
                "csrf": csrf_for(device_id) if expected is not None else "",
                "device_types": sorted(DEVICE_TYPES),
                "series": load_series(conn, device_id, clock(), window),
            }
        return templates.TemplateResponse(request, "device.html", context)

    @protected.post("/devices/{device_id}/edit")
    async def edit_device(request: Request, device_id: int) -> Response:
        if expected is None:
            raise HTTPException(
                status_code=403, detail="Configurer un jeton pour modifier un appareil"
            )
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="Origine refusée")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Origine refusée")
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="Formulaire attendu")
        body = await _read_limited(request, MAX_LOGIN_BYTES)
        if body is None:
            raise HTTPException(status_code=413, detail="Requête trop volumineuse")
        try:
            form = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=4)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Formulaire invalide") from exc
        if (
            not {"csrf", "alias", "device_type"}.issubset(form)
            or not set(form).issubset({"csrf", "alias", "device_type", "mark_known"})
            or any(len(values) != 1 for values in form.values())
            or ("mark_known" in form and form["mark_known"] != ["yes"])
        ):
            raise HTTPException(status_code=422, detail="Champs invalides")
        if not _matches(csrf_for(device_id), form["csrf"][0]):
            raise HTTPException(status_code=403, detail="Protection CSRF invalide")
        await run_in_threadpool(_save_device, settings, device_id, form)
        return RedirectResponse(f"/devices/{device_id}", status_code=303)

    @protected.get("/events", response_class=HTMLResponse)
    def events_page(request: Request) -> Response:
        with database() as conn:
            events = queries.recent_events(conn)
        return templates.TemplateResponse(request, "events.html", {"events": events})

    install_router_dashboard(protected, settings, templates)
    app.include_router(protected)
    return app
