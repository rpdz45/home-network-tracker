"""Explicit Bbox diagnostics in the authenticated local dashboard."""

import os
import secrets
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.routers import bbox
from nettracker.web.bbox_dashboard import install_bbox_dashboard
from nettracker.web.livebox_dashboard import install_livebox_dashboard

MAX_FORM_BYTES = 2048
COOLDOWN_SECONDS = 10
LABELS = {
    bbox.ProbeState.ACCESSIBLE: "Accessible (compatibilité non confirmée)",
    bbox.ProbeState.AUTH_REQUIRED: "Authentification ou droits requis",
    bbox.ProbeState.UNAVAILABLE: "Point de lecture indisponible",
}


def install_router_dashboard(
    protected: APIRouter, settings: Settings, templates: Jinja2Templates
) -> None:
    """Attach routes before include_router; the caller supplies its authenticated router."""
    install_livebox_dashboard(protected, settings, templates)
    install_bbox_dashboard(protected, settings, templates)
    enabled = os.environ.get("NETTRACKER_BBOX_DIAGNOSTICS_ENABLED") == "true"
    raw_address = os.environ.get("NETTRACKER_BBOX_URL", "")
    allow_http = os.environ.get("NETTRACKER_BBOX_ALLOW_HTTP") == "true"
    invalid_address = False
    address = ""
    if raw_address:
        try:
            address = bbox._origin(raw_address, settings.allowed_subnets, allow_http)
        except bbox.BboxError:
            invalid_address = True
    has_token = settings.api.token is not None and bool(settings.api.token.get_secret_value())
    csrf = secrets.token_hex(32)
    lock = Lock()
    last_attempt: float | None = None

    def render(
        request: Request,
        *,
        probes: tuple[bbox.EndpointProbe, ...] = (),
        error: bool = False,
        status_code: int = 200,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "routers.html",
            {
                "enabled": enabled,
                "address": address,
                "allow_http": allow_http,
                "invalid_address": invalid_address,
                "has_token": has_token,
                "can_run": enabled and bool(address) and has_token,
                "csrf": csrf if has_token else "",
                "rows": [{"path": probe.path, "label": LABELS[probe.state]} for probe in probes],
                "error": error,
            },
            status_code=status_code,
        )

    @protected.get("/routers", response_class=HTMLResponse)
    def routers_page(request: Request) -> Response:
        return render(request)

    @protected.post("/routers/bbox/diagnose", response_class=HTMLResponse)
    async def diagnose_bbox(request: Request) -> Response:
        nonlocal last_attempt
        if not has_token or not enabled or not address:
            raise HTTPException(status_code=403, detail="Diagnostic non activé ou jeton absent")
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="Origine refusée")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Origine refusée")
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="Formulaire attendu")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_FORM_BYTES:
                raise HTTPException(status_code=413, detail="Requête trop volumineuse")
            body.extend(chunk)
        try:
            form = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=2
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Formulaire invalide") from exc
        if set(form) != {"csrf", "confirm"} or any(len(values) != 1 for values in form.values()):
            raise HTTPException(status_code=422, detail="Champs invalides")
        if not secrets.compare_digest(csrf.encode(), form["csrf"][0].encode()):
            raise HTTPException(status_code=403, detail="Protection CSRF invalide")
        if form["confirm"] != ["yes"]:
            raise HTTPException(status_code=422, detail="Confirmation requise")
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Diagnostic déjà en cours")
        try:
            now = monotonic()
            if last_attempt is not None and now - last_attempt < COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429, detail="Attendre 10 secondes entre diagnostics"
                )
            last_attempt = now
            try:
                probes = await run_in_threadpool(
                    bbox.read_diagnostic,
                    address,
                    settings.allowed_subnets,
                    enabled=True,
                    allow_http=allow_http,
                )
            except bbox.BboxError:
                return render(request, error=True, status_code=503)
            return render(request, probes=probes)
        finally:
            lock.release()
