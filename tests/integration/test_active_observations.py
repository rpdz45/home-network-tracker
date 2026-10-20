"""Synthetic active observations persist with the correct scan mode and no packets."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_observations
from nettracker.discovery.passive import Neighbor


def test_explicit_active_observations_are_recorded_without_network(tmp_path: Path) -> None:
    conn = connect(tmp_path / "active.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        scope = [IPv4Network("192.168.1.0/24")]
        neighbors = [Neighbor("192.168.1.2", "00:11:22:33:44:55")]
        assert (
            collect_observations(
                repo,
                scope,
                mode="active",
                reader=lambda _: neighbors,
                clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            )
            == 1
        )
        assert tuple(conn.execute("SELECT mode, status FROM scans").fetchone()) == ("active", "ok")
        assert len(repo.list_devices()) == 1
    finally:
        conn.close()
