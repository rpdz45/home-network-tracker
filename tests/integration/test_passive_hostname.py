"""Offline SQLite coverage for scoped optional hostname persistence."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.passive import Neighbor


def test_optional_hostname_persists_only_after_scope_check(tmp_path: Path) -> None:
    conn = connect(tmp_path / "names.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        calls: list[str] = []

        def name(ip: str) -> str:
            calls.append(ip)
            return "device.example"

        assert (
            collect_passive(
                repo,
                [IPv4Network("192.168.1.0/24")],
                reader=lambda _: [Neighbor("192.168.1.2", "00:11:22:33:44:55")],
                clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
                hostname_lookup=name,
            )
            == 1
        )
        assert calls == ["192.168.1.2"]
        assert repo.list_devices()[0].hostname == "device.example"
    finally:
        conn.close()
