"""SQLite and Jinja tests for temporal ICMP history; no network access."""

import sqlite3
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nettracker.errors import DatabaseError
from nettracker.web.formatting import paris_datetime
from nettracker.web.timeseries import load_series

NOW = datetime(2026, 10, 25, 18, tzinfo=UTC)


class TimeSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.execute(
            "CREATE TABLE sightings (device_id INTEGER, source TEXT, online INTEGER, "
            "latency_ms REAL, seen_at TEXT)"
        )
        templates = Path(__file__).resolve().parents[2] / "src/nettracker/web/templates"
        self.env = Environment(
            loader=FileSystemLoader(templates), autoescape=select_autoescape(["html"])
        )
        self.env.filters["paris_datetime"] = paris_datetime

    def tearDown(self) -> None:
        self.conn.close()

    def add(
        self,
        moment: datetime,
        online: bool = True,
        latency: float | None = 1.0,
        source: str = "ping",
        device: int = 1,
    ) -> None:
        self.conn.execute(
            "INSERT INTO sightings VALUES (?, ?, ?, ?, ?)",
            (
                device,
                source,
                int(online),
                latency,
                moment.astimezone(UTC).isoformat(timespec="microseconds"),
            ),
        )

    def render(self, window: str = "24h") -> str:
        series = load_series(self.conn, 1, NOW, window)
        return self.env.get_template("history.html").render(series=series, device={"id": 1})

    def test_empty_window_is_unknown(self) -> None:
        series = load_series(self.conn, 1, NOW)
        self.assertEqual(len(series.buckets), 96)
        self.assertEqual(series.count, 0)
        self.assertIsNone(series.ratio)
        self.assertTrue(all(bucket.status == "unknown" for bucket in series.buckets))
        self.assertIn("Disponibilité inconnue", self.render())

    def test_windows_and_bin_widths(self) -> None:
        self.assertEqual(load_series(self.conn, 1, NOW).minutes, 15)
        self.assertEqual(load_series(self.conn, 1, NOW, "7d").minutes, 105)
        self.assertEqual(len(load_series(self.conn, 1, NOW, "7d").buckets), 96)

    def test_half_open_window_boundaries(self) -> None:
        start = NOW - timedelta(days=1)
        for moment in (start - timedelta(microseconds=1), start, NOW, NOW + timedelta(seconds=1)):
            self.add(moment)
        self.assertEqual(load_series(self.conn, 1, NOW).count, 1)

    def test_microseconds_do_not_round_into_next_bucket(self) -> None:
        boundary = NOW - timedelta(days=1) + timedelta(minutes=15)
        self.add(boundary - timedelta(microseconds=1))
        self.add(boundary)
        series = load_series(self.conn, 1, NOW)
        self.assertEqual(series.buckets[0].count, 1)
        self.assertEqual(series.buckets[1].count, 1)

    def test_discovery_and_other_devices_are_excluded(self) -> None:
        self.add(NOW - timedelta(hours=1, minutes=5), source="discovery")
        self.add(NOW - timedelta(hours=1, minutes=5), device=2)
        self.assertEqual(load_series(self.conn, 1, NOW).count, 0)

    def test_all_samples_are_aggregated_not_only_25(self) -> None:
        for index in range(30):
            self.add(NOW - timedelta(hours=1, minutes=5, seconds=index), latency=float(index))
        series = load_series(self.conn, 1, NOW)
        self.assertEqual(series.count, 30)
        populated = [bucket for bucket in series.buckets if bucket.count]
        self.assertEqual(populated[0].mean_ms, 14.5)
        self.assertEqual(populated[0].peak_ms, 29.0)

    def test_mixed_bucket_and_sample_weighted_ratio(self) -> None:
        self.add(NOW - timedelta(hours=1, minutes=5), latency=10.0)
        self.add(NOW - timedelta(hours=1, minutes=5, seconds=1), online=False, latency=None)
        self.add(NOW - timedelta(hours=1, minutes=5, seconds=2), latency=20.0)
        series = load_series(self.conn, 1, NOW)
        bucket = next(bucket for bucket in series.buckets if bucket.count)
        self.assertEqual(bucket.status, "mixed")
        self.assertEqual(bucket.mean_ms, 15.0)
        self.assertAlmostEqual(series.ratio or 0.0, 200 / 3)

    def test_nonreply_has_no_latency(self) -> None:
        self.add(NOW - timedelta(hours=1, minutes=5), online=False, latency=None)
        series = load_series(self.conn, 1, NOW)
        bucket = next(bucket for bucket in series.buckets if bucket.count)
        self.assertEqual(bucket.status, "no_reply")
        self.assertIsNone(bucket.mean_ms)
        self.assertEqual(series.ratio, 0.0)

    def test_zero_latency_is_valid(self) -> None:
        self.add(NOW - timedelta(hours=1, minutes=5), latency=0.0)
        series = load_series(self.conn, 1, NOW)
        bucket = next(bucket for bucket in series.buckets if bucket.count)
        self.assertEqual(bucket.status, "reply")
        self.assertEqual(bucket.mean_ms, 0.0)
        self.assertEqual(series.scale_ms, 1.0)
        self.assertIn("height: 0.0%;", self.render())

    def test_seven_days_includes_older_samples(self) -> None:
        self.add(NOW - timedelta(days=3))
        self.assertEqual(load_series(self.conn, 1, NOW).count, 0)
        self.assertEqual(load_series(self.conn, 1, NOW, "7d").count, 1)

    def test_timezone_is_normalized_to_utc(self) -> None:
        shifted = NOW.astimezone(timezone(timedelta(hours=2)))
        self.assertEqual(load_series(self.conn, 1, shifted), load_series(self.conn, 1, NOW))

    def test_invalid_parameters(self) -> None:
        for window in ("", "30d", "bad"):
            with self.subTest(window=window), self.assertRaises(ValueError):
                load_series(self.conn, 1, NOW, window)
        with self.assertRaises(ValueError):
            load_series(self.conn, 0, NOW)
        with self.assertRaises(ValueError):
            load_series(self.conn, 1, NOW.replace(tzinfo=None))

    def test_database_error_is_wrapped(self) -> None:
        self.conn.execute("DROP TABLE sightings")
        with self.assertRaises(DatabaseError):
            load_series(self.conn, 1, NOW)

    def test_query_only_connection_works(self) -> None:
        self.conn.execute("PRAGMA query_only = ON")
        self.assertEqual(load_series(self.conn, 1, NOW).count, 0)

    def test_render_has_96_slots_and_period_selection(self) -> None:
        text = self.render("7d")
        self.assertEqual(text.count('class="history-slot"'), 96)
        self.assertIn('value="7d" selected', text)
        self.assertIn("sans mesure", text)
        self.assertIn("pas un uptime temporel", text)

    def render_device(
        self,
        source: str = "discovery",
        online: bool | None = True,
        can_edit: bool = False,
        alias: str = "",
    ) -> str:
        stamp = NOW.isoformat()
        return self.env.get_template("device.html").render(
            device={
                "id": 1,
                "alias": alias,
                "hostname": None,
                "device_type": "phone",
                "vendor": None,
                "mac": "00:11:22:33:44:55",
                "status": "unknown",
                "is_randomized_mac": False,
                "first_seen": stamp,
                "last_seen": stamp,
                "merged_into": None,
            },
            sightings=[
                {
                    "source": source,
                    "online": online,
                    "ip": "192.168.1.20",
                    "latency_ms": None,
                    "packet_loss_pct": None,
                    "seen_at": stamp,
                }
            ],
            events=[
                {
                    "created_at": stamp,
                    "kind": "new_device",
                    "statuses": "dry_run",
                    "details": "<b>fixture</b>",
                }
            ],
            can_edit=can_edit,
            csrf="fixture-csrf",
            device_types=["phone"],
            series=load_series(self.conn, 1, NOW),
        )

    def test_detail_displays_french_identity_and_dates(self) -> None:
        text = self.render_device()
        self.assertIn("Appareil n°1", text)
        self.assertIn("Téléphone", text)
        self.assertIn("À valider", text)
        self.assertIn(">19:00 · 25/10/2026</time>", text)
        self.assertIn("Non disponible à ce stade", text)

    def test_detail_distinguishes_discovery_from_ping(self) -> None:
        text = self.render_device()
        self.assertIn("Observation du cache", text)
        self.assertIn("Présence non vérifiée", text)
        self.assertNotIn("Réponse ICMP reçue", text)

    def test_detail_ping_no_reply_is_not_a_disconnect_claim(self) -> None:
        text = self.render_device(source="ping", online=False)
        self.assertIn("Sans réponse ICMP", text)
        self.assertNotIn("Déconnecté", text)

    def test_detail_escapes_identity_and_event_details(self) -> None:
        text = self.render_device(alias="<script>alert(1)</script>")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;b&gt;fixture&lt;/b&gt;", text)

    def test_detail_preserves_edit_fields_and_readonly_notice(self) -> None:
        text = self.render_device(can_edit=True)
        self.assertIn('name="csrf" value="fixture-csrf"', text)
        self.assertIn('action="/devices/1/edit"', text)
        self.assertIn('name="mark_known" value="yes"', text)
        self.assertIn("Configure un jeton API", self.render_device())

    def test_events_display_local_dates_and_keep_diagnostic_codes(self) -> None:
        text = self.env.get_template("events.html").render(
            events=[
                {
                    "created_at": NOW.isoformat(),
                    "kind": "new_device",
                    "device_id": 1,
                    "alias": None,
                    "hostname": None,
                    "mac": "00:11:22:33:44:55",
                    "statuses": "dry_run",
                    "details": "<b>fixture</b>",
                }
            ]
        )
        self.assertIn(">19:00 · 25/10/2026</time>", text)
        self.assertIn("Appareil n°1", text)
        self.assertIn("new_device", text)
        self.assertIn("dry_run", text)
        self.assertIn("Simulation — aucun envoi", text)
        self.assertIn("&lt;b&gt;fixture&lt;/b&gt;", text)

    def test_history_displays_paris_across_dst_and_keeps_source_instants(self) -> None:
        text = self.render()
        self.assertIn("20:00 · 24/10/2026", text)
        self.assertIn("19:00 · 25/10/2026", text)
        self.assertIn("sources UTC", text)
        self.assertIn("2026-10-25T18:00:00.000000+00:00", text)
