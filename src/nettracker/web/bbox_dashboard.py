"""Explicit authenticated Bbox inventory in the protected dashboard."""

import os
import secrets
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.routers import bbox, bbox_session

MAX_FORM_BYTES = 2048
COOLDOWN_SECONDS = 900


def _text(value: str | None, secret: str) -> str:
    if not value:
        return "Non renseigné"
    return (value.replace(secret, "[masqué]") if secret else value)[:128]


def _label(value: bool | None, positive: str, negative: str) -> str:
    if value is True:
        return positive
    if value is False:
        return negative
    return "Non renseigné"


def install_bbox_dashboard(
    protected: APIRouter, settings: Settings, templates: Jinja2Templates
) -> None:
    """The caller supplies its authenticated router; GET never contacts the Bbox."""
    enabled = os.environ.get("NETTRACKER_BBOX_AUTH_ENABLED") == "true"
    allow_http = os.environ.get("NETTRACKER_BBOX_ALLOW_HTTP") == "true"
    password = SecretStr(os.environ.get("NETTRACKER_BBOX_PASSWORD", ""))
    expected_model = os.environ.get("NETTRACKER_BBOX_EXPECTED_MODEL", "")
    raw_address = os.environ.get("NETTRACKER_BBOX_URL", "")
    raw_ca = os.environ.get("NETTRACKER_BBOX_CA_FILE", "")
    ca_file = Path(raw_ca) if raw_ca else None
    has_password = bool(password.get_secret_value())
    has_model = 1 <= len(expected_model) <= 128
    has_token = settings.api.token is not None and bool(settings.api.token.get_secret_value())
    address = ""
    invalid_address = False
    if raw_address:
        try:
            address = bbox._origin(raw_address, settings.allowed_subnets, allow_http)
        except bbox.BboxError:
            invalid_address = True
    can_read = enabled and bool(address) and has_token and has_password and has_model
    csrf = secrets.token_hex(32)
    lock = Lock()
    last_attempt: float | None = None

    def render(
        request: Request,
        *,
        snapshot: bbox_session.BboxSnapshot | None = None,
        error: bool = False,
        status_code: int = 200,
    ) -> Response:
        secret = password.get_secret_value()
        rows: list[dict[str, str]] = []
        if snapshot:
            for host in snapshot.hosts:
                rows.append(
                    {
                        "name": _text(host.name, secret),
                        "ip": _text(host.address, secret),
                        "mac": _text(host.mac, secret),
                        "state": _label(host.active, "Actif selon la box", "Inactif selon la box"),
                    }
                )
        return templates.TemplateResponse(
            request,
            "bbox.html",
            {
                "enabled": enabled,
                "address": _text(address, secret) if address else "",
                "invalid_address": invalid_address,
                "allow_http": allow_http,
                "has_token": has_token,
                "has_password": has_password,
                "has_model": has_model,
                "can_read": can_read,
                "csrf": csrf if has_token else "",
                "loaded": snapshot is not None,
                "model": _text(snapshot.model, secret) if snapshot else "",
                "firmware": _text(snapshot.firmware, secret) if snapshot else "",
                "session_closed": snapshot.session_closed if snapshot else False,
                "rows": rows,
                "error": error,
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    @protected.get("/routers/bbox", response_class=HTMLResponse)
    def bbox_page(request: Request) -> Response:
        return render(request)

    @protected.post("/routers/bbox/read", response_class=HTMLResponse)
    async def read_bbox(request: Request) -> Response:
        nonlocal last_attempt
        if not can_read:
            raise HTTPException(status_code=403, detail="Lecture Bbox non configurée")
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
            raise HTTPException(status_code=429, detail="Lecture déjà en cours")
        try:
            now = monotonic()
            if last_attempt is not None and now - last_attempt < COOLDOWN_SECONDS:
                raise HTTPException(status_code=429, detail="Attendre 15 minutes entre tentatives")
            last_attempt = now
            try:
                snapshot = await run_in_threadpool(
                    bbox_session.read_authenticated_snapshot,
                    address,
                    settings.allowed_subnets,
                    password,
                    expected_model,
                    enabled=True,
                    confirmed=True,
                    allow_http=allow_http,
                    ca_file=ca_file,
                )
            except bbox.BboxError:
                return render(request, error=True, status_code=503)
            finally:
                last_attempt = monotonic()
            return render(request, snapshot=snapshot)
        finally:
            lock.release()
