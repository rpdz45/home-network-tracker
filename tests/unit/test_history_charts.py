"""Rendering tests for compact ICMP charts; synthetic fixtures only, no network."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def ping(online: bool, latency: float | None, stamp: str) -> dict[str, object]:
    return {"source": "ping", "online": online, "latency_ms": latency, "seen_at": stamp}


class HistoryChartTests(unittest.TestCase):
    def setUp(self) -> None:
        templates = Path(__file__).resolve().parents[2] / "src/nettracker/web/templates"
        self.env = Environment(
            loader=FileSystemLoader(templates), autoescape=select_autoescape(["html"])
        )

    def render(self, samples: list[dict[str, object]]) -> str:
        return self.env.get_template("history.html").render(sightings=samples)

    def test_no_observations_are_unknown(self) -> None:
        text = self.render([])
        self.assertIn("Disponibilité inconnue", text)
        self.assertNotIn('class="icmp-bars"', text)

    def test_discovery_is_not_a_ping(self) -> None:
        text = self.render([{"source": "discovery", "online": True}])
        self.assertIn("Aucune mesure ICMP", text)

    def test_ratio_counts_samples_not_elapsed_time(self) -> None:
        text = self.render([ping(False, None, "later"), ping(True, 10.0, "earlier")])
        self.assertIn("1 réponse(s) sur 2 mesure(s)", text)
        self.assertIn("50.0 %", text)
        self.assertIn("pas un uptime temporel", text)
        self.assertLess(text.index('title="earlier'), text.index('title="later'))

    def test_nonresponse_does_not_become_zero_latency(self) -> None:
        text = self.render([ping(False, None, "fixture")])
        self.assertIn('class="icmp-no-latency"', text)
        self.assertNotIn('class="icmp-bar" style=', text)
        self.assertIn("0.0 %", text)

    def test_zero_latency_is_a_valid_response(self) -> None:
        text = self.render([ping(True, 0.0, "fixture")])
        self.assertIn('class="icmp-bar" style="height: 0.0%;"', text)
        self.assertIn("100.0 %", text)

    def test_labels_are_escaped(self) -> None:
        text = self.render([ping(True, 1.0, '<script>"')])
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("&#34;", text)

    def test_only_25_recent_observations_are_considered(self) -> None:
        observations: list[dict[str, object]] = [{"source": "discovery"} for _ in range(25)]
        observations.append(ping(True, 1.0, "older"))
        self.assertIn("Aucune mesure ICMP", self.render(observations))
