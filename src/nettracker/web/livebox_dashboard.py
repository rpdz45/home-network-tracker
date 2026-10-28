"""Explicit administrator-backed Livebox reads; never change router access rules."""

import os
import secrets
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.routers import livebox5

MAX_FORM_BYTES = 2048
COOLDOWN_SECONDS = 60


def _safe_text(value: object, secret: str) -> str:
    if not isinstance(value, str) or not value:
        return "Non renseigné"
    text = value.replace(secret, "[masqué]") if secret else value
    return text[:120]


def _device_rows(devices: tuple[dict[str, Any], ...], secret: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for device in devices:
        active = device.get("Active")
        state = "État non renseigné"
        if active is True:
            state = "Actif selon la box"
        elif active is False:
            state = "Inactif selon la box"
        rows.append(
            {
                "name": _safe_text(device.get("Name"), secret),
                "ip": _safe_text(device.get("IPAddress"), secret),
                "mac": _safe_text(device.get("PhysAddress"), secret),
                "state": state,
            }
        )
    return rows


def install_livebox_dashboard(
    protected: APIRouter, settings: Settings, templates: Jinja2Templates
) -> None:
    """Use only the caller's authenticated router and the existing read-only client."""
    enabled = os.environ.get("NETTRACKER_LIVEBOX5_ENABLED") == "true"
    allow_http = os.environ.get("NETTRACKER_LIVEBOX5_ALLOW_HTTP") == "true"
    raw_address = os.environ.get("NETTRACKER_LIVEBOX5_URL", "")
    password = SecretStr(os.environ.get("NETTRACKER_LIVEBOX5_PASSWORD", ""))
    has_password = bool(password.get_secret_value())
    has_token = settings.api.token is not None and bool(settings.api.token.get_secret_value())
    address = ""
    invalid_address = False
    if raw_address:
        try:
            endpoint = livebox5._endpoint(raw_address, settings.allowed_subnets, allow_http)
            address = endpoint.removesuffix("/ws")
        except livebox5.LiveboxError:
            invalid_address = True
    csrf = secrets.token_hex(32)
    lock = Lock()
    last_attempt: float | None = None

    def render(
        request: Request,
        *,
        snapshot: livebox5.LiveboxSnapshot | None = None,
        error: bool = False,
        status_code: int = 200,
    ) -> Response:
        secret = password.get_secret_value()
        return templates.TemplateResponse(
            request,
            "livebox.html",
            {
                "enabled": enabled,
                "address": address,
                "invalid_address": invalid_address,
                "allow_http": allow_http,
                "has_token": has_token,
                "has_password": has_password,
                "can_read": enabled and bool(address) and has_token and has_password,
                "csrf": csrf if has_token else "",
                "loaded": snapshot is not None,
                "firmware": _safe_text(snapshot.firmware, secret) if snapshot else "",
                "rows": _device_rows(snapshot.devices, secret) if snapshot else [],
                "error": error,
            },
            status_code=status_code,
        )

    @protected.get("/routers/livebox", response_class=HTMLResponse)
    def livebox_page(request: Request) -> Response:
        return render(request)

    @protected.post("/routers/livebox/read", response_class=HTMLResponse)
    async def read_livebox(request: Request) -> Response:
        nonlocal last_attempt
        if not enabled or not address or not has_token or not has_password:
            raise HTTPException(status_code=403, detail="Lecture Livebox non configurée")
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
                raise HTTPException(status_code=429, detail="Attendre 60 secondes entre lectures")
            last_attempt = now
            try:
                snapshot = await run_in_threadpool(
                    livebox5.read_snapshot,
                    address,
                    settings.allowed_subnets,
                    password,
                    enabled=True,
                    allow_http=allow_http,
                )
            except livebox5.LiveboxError:
                return render(request, error=True, status_code=503)
            return render(request, snapshot=snapshot)
        finally:
            lock.release()
