"""Explicit Fing identification view; never overwrite local device identities."""

import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from nettracker.config import Settings
from nettracker.discovery import fing
from nettracker.errors import NetTrackerError
from nettracker.web import queries

MAX_FORM_BYTES = 2048
COOLDOWN_SECONDS = 60


@dataclass(frozen=True)
class FingRow:
    local_id: int | None
    local_name: str
    name: str
    manufacturer: str
    model: str
    device_type: str
    addresses: tuple[str, ...]
    mac: str
    association: str
    state: str


def _text(value: object, secret: str) -> str:
    if not isinstance(value, str):
        return "Non identifié"
    text = value.replace(secret, "[masqué]") if secret else value
    return " ".join(text.split())[:128] or "Non identifié"


def identity_rows(
    inventory: fing.FingInventory, local_rows: list[sqlite3.Row], secret: str
) -> tuple[FingRow, ...]:
    matches: dict[str, list[sqlite3.Row]] = {}
    for record in local_rows:
        mac, ip, identifier = record["mac"], record["ip"], record["id"]
        if not isinstance(mac, str) or not isinstance(ip, str) or type(identifier) is not int:
            continue
        if identifier <= 0:
            continue
        try:
            matched = fing.match_identity(inventory, mac, ip)
        except fing.FingError:
            matched = None
        if matched is not None:
            matches.setdefault(matched.mac, []).append(record)
    rows: list[FingRow] = []
    for device in inventory.devices:
        candidates = matches.get(device.mac, [])
        local = candidates[0] if len(candidates) == 1 else None
        association = "MAC et IP concordantes"
        if not candidates:
            association = "Pas de correspondance dans la liste locale"
        elif len(candidates) > 1:
            association = "Correspondance locale ambiguë : aucun lien créé"
        rows.append(
            FingRow(
                local["id"] if local is not None else None,
                _text(local["alias"] or local["hostname"], secret) if local is not None else "—",
                _text(device.name, secret),
                _text(device.manufacturer, secret),
                _text(device.model, secret),
                _text(device.device_type, secret),
                device.addresses,
                device.mac,
                association,
                "Actif selon Fing" if device.reported_state == "UP" else "Inactif selon Fing",
            )
        )
    return tuple(rows)


def _load_rows(settings: Settings) -> list[sqlite3.Row]:
    if not settings.database_path.is_file():
        raise NetTrackerError("local inventory is not initialized")
    with closing(queries.open_readonly(settings.database_path)) as connection:
        return queries.list_devices(connection)


def install_fing_dashboard(
    protected: APIRouter, settings: Settings, templates: Jinja2Templates
) -> None:
    """Install on the existing authenticated router; only confirmed POST reads Fing."""
    enabled = os.environ.get("NETTRACKER_FING_ENABLED") == "true"
    api_key = SecretStr(os.environ.get("NETTRACKER_FING_API_KEY", ""))
    has_key = 1 <= len(api_key.get_secret_value()) <= 4096
    has_token = settings.api.token is not None and bool(settings.api.token.get_secret_value())
    can_read = enabled and has_key and has_token
    csrf = secrets.token_hex(32)
    lock = Lock()
    last_attempt: float | None = None

    def load() -> tuple[fing.FingInventory, tuple[FingRow, ...]]:
        local_rows = _load_rows(settings)
        inventory = fing.read_inventory(
            api_key, settings.allowed_subnets, enabled=True, confirmed=True
        )
        return inventory, identity_rows(inventory, local_rows, api_key.get_secret_value())

    def render(
        request: Request,
        *,
        inventory: fing.FingInventory | None = None,
        rows: tuple[FingRow, ...] = (),
        error: bool = False,
        status_code: int = 200,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "fing.html",
            {
                "enabled": enabled,
                "has_key": has_key,
                "has_token": has_token,
                "can_read": can_read,
                "csrf": csrf if has_token else "",
                "loaded": inventory is not None,
                "retrieved_at": inventory.retrieved_at.isoformat() if inventory else "",
                "excluded": inventory.excluded_devices if inventory else 0,
                "rows": rows,
                "error": error,
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    @protected.get("/identification/fing", response_class=HTMLResponse)
    def fing_page(request: Request) -> Response:
        return render(request)

    @protected.post("/identification/fing/read", response_class=HTMLResponse)
    async def read_fing(request: Request) -> Response:
        nonlocal last_attempt
        if not can_read:
            raise HTTPException(status_code=403, detail="Lecture Fing non configurée")
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
                inventory, rows = await run_in_threadpool(load)
            except NetTrackerError:
                return render(request, error=True, status_code=503)
            finally:
                last_attempt = monotonic()
            return render(request, inventory=inventory, rows=rows)
        finally:
            lock.release()
