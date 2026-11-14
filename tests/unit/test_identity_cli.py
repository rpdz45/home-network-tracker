"""CLI integration with a temporary inventory and injected DNS transport."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nettracker.db import Repository, connect, migrate
from nettracker.db.network_identity import current_observations
from nettracker.entrypoint import main


def write_config(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "devices.db"
    config = tmp_path / "config.toml"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    return config, database


def test_without_authorization_does_not_create_database(tmp_path: Path) -> None:
    config, database = write_config(tmp_path)
    assert main(
        ["identify-dns", "-c", str(config), "--device-id", "1", "--dns-server", "192.168.1.1"]
    ) == 1
    assert not database.exists()


def test_authorized_missing_database_is_not_created(tmp_path: Path) -> None:
    config, database = write_config(tmp_path)
    assert main(
        [
            "identify-dns",
            "-c",
            str(config),
            "--device-id",
            "1",
            "--dns-server",
            "192.168.1.1",
            "--enable-dns",
        ]
    ) == 1
    assert not database.exists()


def test_command_persists_dns_with_simulated_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, database = write_config(tmp_path)
    conn = connect(database)
    try:
        migrate(conn)
        repo = Repository(conn)
        now = datetime.now(UTC)
        device = repo.upsert_device("02:00:00:00:00:20", seen_at=now)
        repo.add_sighting(device_id=device.id, ip="192.168.1.20", online=True, seen_at=now)
    finally:
        conn.close()

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        assert (ip, server, timeout) == ("192.168.1.20", "192.168.1.1", 1.5)
        return ("NAS.test.",)

    monkeypatch.setattr("nettracker.discovery.router_dns._query_ptr", lookup)
    assert main(
        [
            "identify-dns",
            "-c",
            str(config),
            "--device-id",
            str(device.id),
            "--dns-server",
            "192.168.1.1",
            "--enable-dns",
        ]
    ) == 0
    conn = connect(database)
    try:
        assert current_observations(conn, device.id)[0]["value"] == "nas.test"
    finally:
        conn.close()
