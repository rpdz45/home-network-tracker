"""Optional Fing fields must render safely under strict Jinja validation."""

from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

from nettracker.web.formatting import paris_datetime

TEMPLATES = Path(__file__).resolve().parents[2] / "src/nettracker/web/templates"


def render(extra: dict[str, object]) -> str:
    env = Environment(
        loader=ChoiceLoader(
            [
                DictLoader(
                    {
                        "base.html": "{% block content %}{% endblock %}",
                        "device_information.html": (
                            "{% macro collection_summary(health) %}{% endmacro %}"
                            "{% macro mac_note(value) %}{% endmacro %}"
                            "{% macro information_guide() %}{% endmacro %}"
                        ),
                    }
                ),
                FileSystemLoader(TEMPLATES),
            ]
        ),
        undefined=StrictUndefined,
        autoescape=True,
    )
    env.filters["paris_datetime"] = paris_datetime
    device: dict[str, object] = {
        "id": 50,
        "alias": "",
        "hostname": "",
        "mac": "02:00:00:00:00:01",
        "ip": None,
        "vendor": None,
        "status": "unknown",
        "is_randomized_mac": True,
        "ping_online": None,
        "last_seen": "2026-10-28T14:07:00Z",
    }
    device.update(extra)
    return env.get_template("devices.html").render(
        devices=[device], health={}, monitoring_enabled=False
    )


def test_missing_fing_fields_render_under_strict_undefined() -> None:
    text = render({})
    assert "Appareil n°50" in text
    assert "Nom à renseigner" in text
    assert "Aucune identification enregistrée" in text


@pytest.mark.parametrize("value", [None, ""])
def test_empty_fing_source_is_optional(value: str | None) -> None:
    assert "Aucune identification enregistrée" in render({"fing_source": value})


def test_partial_report_keeps_unknown_values() -> None:
    text = render({"fing_source": "fing_local_api"})
    assert text.count("Non identifié") == 3
    assert "Récupération API : Non renseigné" in text


@pytest.mark.parametrize(
    ("alias", "hostname", "expected"),
    [("Personal", "network", "Personal"), ("", "network", "network"), ("", "", "Reported")],
)
def test_name_priority(alias: str, hostname: str, expected: str) -> None:
    text = render({"alias": alias, "hostname": hostname, "fing_name": "Reported"})
    assert f">{expected}</a>" in text


def test_reported_fields_remain_escaped() -> None:
    payload = "<script>fixture()</script>"
    text = render(
        {
            "fing_source": "fing_local_api",
            "fing_name": payload,
            "fing_manufacturer": payload,
            "fing_model": payload,
            "fing_retrieved_at": "2026-10-28T14:07:00Z",
        }
    )
    assert payload not in text
    assert text.count("&lt;script&gt;fixture()&lt;/script&gt;") == 4
    assert "15:07 · 28/10/2026" in text
