"""Vendor enrichment uses injected data and a local SQLite database only."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.passive import Neighbor


def test_offline_vendor_persisted_but_random_mac_remains_unknown(tmp_path: Path) -> None:
    conn = connect(tmp_path / "vendors.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        entries = [
            Neighbor("192.168.1.2", "00:1a:2b:00:00:01"),
            Neighbor("192.168.1.3", "02:1a:2b:00:00:02"),
        ]
        assert (
            collect_passive(
                repo,
                [IPv4Network("192.168.1.0/24")],
                reader=lambda _: entries,
                clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
                vendors={"001A2B": "Example Devices Inc."},
            )
            == 2
        )
        devices = {device.mac: device for device in repo.list_devices()}
        assert devices["00:1a:2b:00:00:01"].vendor == "Example Devices Inc."
        assert devices["02:1a:2b:00:00:02"].vendor is None
        assert devices["02:1a:2b:00:00:02"].status == "to_confirm"
    finally:
        conn.close()
