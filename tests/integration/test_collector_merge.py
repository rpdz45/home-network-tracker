"""Offline integration test of conservative suggestions during discovery."""

from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.passive import Neighbor

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_new_random_mac_suggests_once_without_merging(tmp_path: Path) -> None:
    conn = connect(tmp_path / "collector.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        old = repo.upsert_device("00:11:22:33:44:55", seen_at=NOW, hostname="phone.local")
        repo.set_status(old.id, "known")
        network = [IPv4Network("192.168.1.0/24")]
        reader = lambda _: [Neighbor("192.168.1.5", "02:11:22:33:44:77")]
        clock = lambda: NOW + timedelta(hours=1)
        lookup = lambda _: "phone.local"
        assert collect_passive(repo, network, reader=reader, clock=clock, hostname_lookup=lookup) == 1
        assert collect_passive(repo, network, reader=reader, clock=clock, hostname_lookup=lookup) == 1
        events = repo.list_events(kind="merge_suggested")
        assert len(events) == 1
        assert events[0].details == {"candidate_device_id": old.id}
        new = repo.get_device_by_mac("02:11:22:33:44:77")
        assert new is not None
        assert new.status == "to_confirm"
        assert new.merged_into is None
        assert len(repo.list_devices()) == 2
    finally:
        conn.close()
