"""Offline template checks: data freshness and identity labels, no network."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from nettracker.web.formatting import paris_datetime

TEMPLATES = Path(__file__).resolve().parents[2] / "src/nettracker/web/templates"
STAMP = "2026-10-28T14:07:00Z"


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
    )
    env.filters["paris_datetime"] = paris_datetime
    return env


def render_list(
    age: float | None = 0,
    *,
    last: str | None = STAMP,
    stale: bool = False,
    private: bool = False,
    alias: str = "Mon appareil",
) -> str:
    device = {
        "id": 1,
        "alias": alias,
        "hostname": "nom-annonce",
        "ip": "192.168.1.20",
        "mac": "02:00:00:00:00:01",
        "vendor": None,
        "status": "to_confirm",
        "is_randomized_mac": private,
        "ping_online": None,
        "last_seen": STAMP,
    }
    return (
        environment()
        .get_template("devices.html")
        .render(
            devices=[device],
            health={"last_success_at": last, "age_seconds": age, "stale": stale},
            monitoring_enabled=False,
        )
    )


@pytest.mark.parametrize(
    ("age", "last", "stale", "status", "elapsed"),
    [
        (None, None, False, "aucune collecte réussie", None),
        (None, STAMP, False, "ancienneté inconnue", "ancienneté inconnue"),
        (0, STAMP, False, "collecte récente", "moins d'une minute"),
        (60, STAMP, False, "collecte récente", "1 min"),
        (900, STAMP, False, "collecte récente", "15 min"),
        (901, STAMP, True, "à actualiser", "15 min"),
        (7500, STAMP, True, "à actualiser", "2 h 5 min"),
        (90061, STAMP, True, "à actualiser", "1 j 1 h 1 min"),
        (-1, STAMP, False, "horodatage à vérifier", "horodatage dans le futur"),
    ],
)
def test_collection_states(
    age: float | None, last: str | None, stale: bool, status: str, elapsed: str | None
) -> None:
    text = render_list(age, last=last, stale=stale)
    assert "Découverte : " + status in text
    assert "Collecteur : périmé" not in text
    if elapsed is not None:
        assert elapsed in text
    if last is not None:
        assert "15:07 · 28/10/2026" in text
    if stale:
        assert "ni intrusion" in text


def test_local_mac_is_not_presented_as_an_intruder() -> None:
    text = render_list(private=True)
    assert "Adresse MAC locale (privée possible)" in text
    assert "ce n'est pas un signe d'intrusion" in text
    assert "À confirmer" in text
    assert "MAC privée / locale" not in text


def test_global_mac_has_no_local_badge() -> None:
    assert "Adresse MAC locale (privée possible)" not in render_list(private=False)


def test_identity_and_presence_are_not_confused() -> None:
    text = render_list()
    for explanation in [
        "Fabricant réseau (interface)",
        "Validation personnelle",
        "Pas encore mesuré",
        "Les résultats ICMP sont historiques",
        "Ignoré",
        "ne bloque aucun accès",
        "pas la preuve qu'un processus tourne",
        "ne relance pas la collecte",
    ]:
        assert explanation in text
    assert 'href="/identification/fing"' in text
    assert "<form" not in text


def test_untrusted_names_are_still_escaped() -> None:
    text = render_list(alias="<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>" not in text


def test_partial_legacy_context_does_not_invent_freshness() -> None:
    text = (
        environment()
        .get_template("devices.html")
        .render(devices=[], health={"last_success_at": STAMP}, monitoring_enabled=False)
    )
    assert "Découverte : ancienneté inconnue" in text
    assert "Découverte : collecte récente" not in text


def test_detail_preserves_edit_form_and_explains_identity() -> None:
    device = {
        "id": 1,
        "alias": "<img src=x onerror=alert(1)>",
        "hostname": "nom-annonce",
        "device_type": None,
        "vendor": None,
        "mac": "02:00:00:00:00:01",
        "is_randomized_mac": True,
        "status": "to_confirm",
        "first_seen": STAMP,
        "last_seen": STAMP,
        "merged_into": None,
    }
    series = {
        "window": "24h",
        "start": STAMP,
        "end": STAMP,
        "minutes": 15,
        "scale_ms": 1,
        "buckets": [],
        "ratio": None,
    }
    text = (
        environment()
        .get_template("device.html")
        .render(
            device=device,
            can_edit=True,
            csrf="synthetic-csrf",
            device_types=["computer"],
            series=series,
            sightings=[],
            events=[],
        )
    )
    assert "&lt;img" in text
    assert "<img src=x" not in text
    assert 'action="/devices/1/edit"' in text
    assert 'name="csrf" value="synthetic-csrf"' in text
    assert "Adresse MAC locale (privée possible)" in text
    assert "Consulter les modèles fournis par Fing" in text
    assert "Ignorer ou effacer une fiche ne coupe ni le Wi-Fi ni Internet" in text
    assert "Historique ICMP" in text
