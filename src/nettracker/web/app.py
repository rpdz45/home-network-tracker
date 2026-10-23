"""Read-only local dashboard (FastAPI + Jinja2). It never scans and never writes."""

import logging
import secrets
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from nettracker.config import Settings
from nettracker.db.health import CollectorHealth, collector_health
from nettracker.errors import NetTrackerError
from nettracker.web import queries

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
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


def create_app(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Build the dashboard. Without a configured token it is meant for loopback only."""
    expected = _expected_credential(settings)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app = FastAPI(title="Home Network Tracker", docs_url=None, redoc_url=None, openapi_url=None)

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
        }
        return templates.TemplateResponse(request, "devices.html", context)

    @protected.get("/devices/{device_id}", response_class=HTMLResponse)
    def device_page(request: Request, device_id: int) -> Response:
        with database() as conn:
            device = queries.get_device(conn, device_id)
            if device is None:
                raise HTTPException(status_code=404, detail="Appareil introuvable")
            context = {
                "device": device,
                "sightings": queries.device_sightings(conn, device_id),
                "events": queries.device_events(conn, device_id),
            }
        return templates.TemplateResponse(request, "device.html", context)

    @protected.get("/events", response_class=HTMLResponse)
    def events_page(request: Request) -> Response:
        with database() as conn:
            events = queries.recent_events(conn)
        return templates.TemplateResponse(request, "events.html", {"events": events})

    app.include_router(protected)
    return app
