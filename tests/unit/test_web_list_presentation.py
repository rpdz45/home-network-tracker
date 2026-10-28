"""Offline rendering and in-process routing checks for the device list."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from nettracker.web.formatting import paris_datetime

TEMPLATES = Path(__file__).resolve().parents[2] / "src/nettracker/web/templates"


def render_list(
    *,
    status: str = "unknown",
    online: int | None = None,
    enabled: bool = False,
    alias: str = "",
    empty: bool = False,
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["paris_datetime"] = paris_datetime
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        device = conn.execute(
            "SELECT 50 AS id, ? AS alias, '' AS hostname, '00:11:22:33:44:55' AS mac, "
            "'192.168.1.20' AS ip, NULL AS vendor, ? AS status, 0 AS is_randomized_mac, "
            "? AS ping_online, '2026-10-28T14:07:00Z' AS last_seen",
            (alias, status, online),
        ).fetchone()
        return env.get_template("devices.html").render(
            devices=[] if empty else [device],
            health={"last_success_at": "2026-10-28T14:07:00Z"},
            health_label="OK",
            health_class="ok",
            monitoring_enabled=enabled,
        )
    finally:
        conn.close()


def test_list_displays_paris_dates_and_fallback_name() -> None:
    text = render_list()
    assert "15:07 · 28/10/2026" in text
    assert "2026-10-28T14:07:00Z" not in text
    assert "Appareil n°50" in text
    assert "À valider" in text
    assert "Pas encore mesuré" in text
    assert "Suivi configuré : désactivé" in text


@pytest.mark.parametrize(
    ("status", "label"),
    [("known", "Reconnu"), ("to_confirm", "À confirmer"), ("ignored", "Ignoré")],
)
def test_list_translates_validation(status: str, label: str) -> None:
    assert label in render_list(status=status)


@pytest.mark.parametrize(("online", "label"), [(1, "Réponse reçue"), (0, "Sans réponse")])
def test_list_distinguishes_ping_results(online: int, label: str) -> None:
    text = render_list(online=online, enabled=True)
    assert label in text
    assert "Suivi configuré : activé" in text
    assert "Les résultats ICMP sont historiques" in text


def test_list_escapes_aliases() -> None:
    text = render_list(alias="<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>" not in text


def test_list_explains_empty_inventory() -> None:
    assert "Aucun appareil enregistré" in render_list(empty=True)


def test_app_registers_date_filter_and_monitoring_context(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from nettracker.config import Settings
    from nettracker.db import Repository, connect, migrate
    from nettracker.web.app import create_app

    now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    settings = Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(tmp_path / "presentation.db"),
            "monitor": {"enabled": False},
        }
    )
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        Repository(conn).upsert_device("00:11:22:33:44:55", seen_at=now)
    finally:
        conn.close()
    with TestClient(create_app(settings, clock=lambda: now)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "11:00 · 28/10/2026" in response.text
    assert "Suivi configuré : désactivé" in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
