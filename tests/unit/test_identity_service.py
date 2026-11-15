"""DNS service tests use injected lookups and temporary SQLite only."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.db import Repository, connect, migrate
from nettracker.db.network_identity import current_observations
from nettracker.discovery.identity_service import enrich_router_dns
from nettracker.discovery.router_dns import DNSLookupFailure

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
NETWORKS = (IPv4Network("192.168.1.0/24"),)


@pytest.fixture
def inventory(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, int]]:
    conn = connect(tmp_path / "identity.db")
    migrate(conn)
    repo = Repository(conn)
    device = repo.upsert_device("02:00:00:00:00:20", seen_at=NOW)
    repo.add_sighting(device_id=device.id, ip="192.168.1.20", online=True, seen_at=NOW)
    try:
        yield conn, device.id
    finally:
        conn.close()


def test_dns_is_stored_without_changing_device(inventory: tuple[sqlite3.Connection, int]) -> None:
    conn, device_id = inventory
    before = tuple(conn.execute("SELECT * FROM devices").fetchone())

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        assert (ip, server, timeout) == ("192.168.1.20", "192.168.1.1", 1.5)
        assert not conn.in_transaction
        return ("NAS.test.",)

    assert enrich_router_dns(
        conn,
        device_id=device_id,
        server="192.168.1.1",
        allowed_subnets=NETWORKS,
        enabled=True,
        lookup=lookup,
        clock=lambda: NOW,
    ) == 1
    row = current_observations(conn, device_id)[0]
    assert (row["value"], row["source"], row["endpoint"]) == (
        "nas.test",
        "dns_ptr",
        "192.168.1.1",
    )
    assert tuple(conn.execute("SELECT * FROM devices").fetchone()) == before


@pytest.mark.parametrize("reason", ["disabled", "ignored", "outside", "transaction"])
def test_refusals_never_query_dns(
    inventory: tuple[sqlite3.Connection, int], reason: str
) -> None:
    conn, device_id = inventory
    if reason == "ignored":
        conn.execute("UPDATE devices SET status = 'ignored'")
    if reason == "transaction":
        conn.execute("BEGIN")

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        pytest.fail("DNS must not be called")

    with pytest.raises(ValueError):
        enrich_router_dns(
            conn,
            device_id=device_id,
            server="8.8.8.8" if reason == "outside" else "192.168.1.1",
            allowed_subnets=NETWORKS,
            enabled=reason != "disabled",
            lookup=lookup,
            clock=lambda: NOW,
        )


def test_binding_change_during_lookup_prevents_storage(
    inventory: tuple[sqlite3.Connection, int],
) -> None:
    conn, device_id = inventory

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        conn.execute("UPDATE sightings SET ip = '192.168.1.21'")
        return ("nas.test.",)

    with pytest.raises(ValueError, match="binding"):
        enrich_router_dns(
            conn,
            device_id=device_id,
            server="192.168.1.1",
            allowed_subnets=NETWORKS,
            enabled=True,
            lookup=lookup,
            clock=lambda: NOW,
        )
    assert conn.execute("SELECT COUNT(*) FROM network_identity_observations").fetchone()[0] == 0


def test_timeout_is_recorded(inventory: tuple[sqlite3.Connection, int]) -> None:
    conn, device_id = inventory

    def lookup(ip: str, server: str, timeout: float) -> tuple[str, ...]:
        raise DNSLookupFailure("timeout")

    assert enrich_router_dns(
        conn,
        device_id=device_id,
        server="192.168.1.1",
        allowed_subnets=NETWORKS,
        enabled=True,
        lookup=lookup,
        clock=lambda: NOW,
    ) == 1
    row = current_observations(conn, device_id)[0]
    assert row["status"] == "timeout"
    assert row["value"] is None
