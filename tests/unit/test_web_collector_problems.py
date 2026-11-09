"""Read-only collector problems: in-process HTTP and synthetic SQLite fixtures."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nettracker.config import Settings
from nettracker.db import Repository, connect, migrate
from nettracker.db.repository import ScanStatus
from nettracker.web.app import create_app

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TITLE = "Problèmes récents de découverte"
HIDDEN = "private-value-not-for-display"


@pytest.fixture
def dashboard(tmp_path: Path) -> Iterator[tuple[Settings, TestClient]]:
    settings = Settings.model_validate(
        {"allowed_subnets": ["192.168.1.0/24"], "database_path": tmp_path / "health.db"}
    )
    conn = connect(settings.database_path)
    try:
        migrate(conn)
    finally:
        conn.close()
    with TestClient(create_app(settings, clock=lambda: NOW)) as client:
        yield settings, client


def add_scan(
    settings: Settings,
    *,
    minutes_ago: int = 1,
    status: ScanStatus = "error",
    error: str | None = None,
    finished: bool = True,
) -> None:
    conn = connect(settings.database_path)
    try:
        repo = Repository(conn)
        started = NOW - timedelta(minutes=minutes_ago)
        scan = repo.start_scan(mode="passive", started_at=started)
        if finished:
            repo.finish_scan(
                scan, status=status, finished_at=started + timedelta(seconds=1), error=error
            )
    finally:
        conn.close()


def snapshot(settings: Settings) -> str:
    conn = connect(settings.database_path)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def problem_rows(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    assert TITLE in response.text
    text: str = response.text
    return text.split('<tbody id="collector-problems">', 1)[1].split("</tbody>", 1)[0]


def test_empty_history_is_explicit(dashboard: tuple[Settings, TestClient]) -> None:
    _, client = dashboard
    text = client.get("/").text
    assert TITLE in text
    assert "Aucun problème de découverte enregistré." in text
    assert "aucune collecte réussie" in text


def test_success_does_not_appear_as_a_problem(dashboard: tuple[Settings, TestClient]) -> None:
    settings, client = dashboard
    add_scan(settings, status="ok")
    text = client.get("/").text
    assert "Aucun problème de découverte enregistré." in text
    assert "collecte récente" in text


@pytest.mark.parametrize(
    ("error", "label"),
    [
        ("PermissionError", "Permission refusée"),
        ("TimeoutError", "Délai dépassé"),
        ("OSError", "Erreur système"),
        ("DatabaseError", "Erreur de base de données"),
        ("ValueError", "Données invalides"),
        (None, "Erreur de collecte (détail masqué)"),
        (HIDDEN, "Erreur de collecte (détail masqué)"),
    ],
)
def test_problem_categories_without_a_success(
    dashboard: tuple[Settings, TestClient], error: str | None, label: str
) -> None:
    settings, client = dashboard
    add_scan(settings, error=error)
    rows = problem_rows(client)
    assert label in rows
    assert "Échec" in rows
    assert "12:59 · 09/11/2026" in rows
    assert HIDDEN not in rows
    assert "aucune collecte réussie" in client.get("/").text


def test_unfinished_scan_is_not_claimed_as_a_failure(
    dashboard: tuple[Settings, TestClient],
) -> None:
    settings, client = dashboard
    add_scan(settings, finished=False)
    rows = problem_rows(client)
    assert "Non terminé à la lecture" in rows
    assert "Échec" not in rows
    assert "En cours ou interrompu" in rows


def test_denied_scan_is_distinguished(dashboard: tuple[Settings, TestClient]) -> None:
    settings, client = dashboard
    add_scan(settings, status="denied", error="PermissionError")
    assert "Refusé" in problem_rows(client)


def test_only_five_latest_problem_records_are_shown(
    dashboard: tuple[Settings, TestClient],
) -> None:
    settings, client = dashboard
    for minute in range(8, 0, -1):
        add_scan(settings, minutes_ago=minute, error="TimeoutError")
    add_scan(settings, status="ok")
    rows = problem_rows(client)
    assert rows.count("<tr>") == 5
    assert "12:55 · 09/11/2026" in rows
    assert "12:59 · 09/11/2026" in rows
    assert "12:54 · 09/11/2026" not in rows
    assert rows.index("12:59") < rows.index("12:55")


@pytest.mark.parametrize("age", [1, 16])
def test_problem_history_does_not_override_freshness(
    dashboard: tuple[Settings, TestClient], age: int
) -> None:
    settings, client = dashboard
    add_scan(settings, status="ok", minutes_ago=age)
    add_scan(settings, error="TimeoutError")
    text = client.get("/").text
    expected = "collecte récente" if age == 1 else "à actualiser"
    assert expected in text
    assert "Délai dépassé" in problem_rows(client)


@pytest.mark.parametrize("field", ["error", "started_at", "finished_at"])
def test_database_details_never_reach_html(
    dashboard: tuple[Settings, TestClient], field: str
) -> None:
    settings, client = dashboard
    add_scan(settings, error="TimeoutError")
    payload = f"<script>{HIDDEN}</script>"
    conn = connect(settings.database_path)
    try:
        statements = {
            "error": "UPDATE scans SET error = ?",
            "started_at": "UPDATE scans SET started_at = ?",
            "finished_at": "UPDATE scans SET finished_at = ?",
        }
        conn.execute(statements[field], (payload,))
    finally:
        conn.close()
    text = client.get("/").text
    assert TITLE in text
    assert HIDDEN not in text
    assert "<script>" not in text
    if field != "error":
        assert "Date invalide" in text


def test_gets_leave_database_unchanged(dashboard: tuple[Settings, TestClient]) -> None:
    settings, client = dashboard
    add_scan(settings, status="ok", minutes_ago=20)
    add_scan(settings, error="PermissionError")
    before = snapshot(settings)
    for _ in range(2):
        assert "Permission refusée" in problem_rows(client)
    assert snapshot(settings) == before
    response = client.get("/")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")


def test_configured_authentication_protects_problem_history(
    dashboard: tuple[Settings, TestClient],
) -> None:
    settings, _ = dashboard
    add_scan(settings, error="PermissionError")
    protected = Settings.model_validate(
        {**settings.model_dump(), "api": {"token": "synthetic-dashboard-credential"}}
    )
    with TestClient(create_app(protected, clock=lambda: NOW)) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert TITLE not in response.text
        response = client.get(
            "/", headers={"Authorization": "Bearer synthetic-dashboard-credential"}
        )
        assert response.status_code == 200
        assert "Permission refusée" in response.text
