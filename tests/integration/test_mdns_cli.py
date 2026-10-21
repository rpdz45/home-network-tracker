"""CLI/SQLite integration with invented observations and mocked mDNS transport."""

from ipaddress import IPv4Network
from pathlib import Path
from unittest.mock import Mock

import dns.message
import dns.rrset
import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.strategy import DiscoveryResult


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in (
        "NETTRACKER_CONFIG",
        "NETTRACKER_DATABASE_PATH",
        "NETTRACKER_API_TOKEN",
        "NETTRACKER_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def config(tmp_path: Path, *, enabled: bool = True, active: bool = False) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "devices.db"\n'
        f"[scan]\nmdns_enabled = {str(enabled).lower()}\n"
        f'mode = "{"active" if active else "passive"}"\nmdns_timeout_seconds = 0.5\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("configured", [False, True])
def test_config_alone_never_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    path = config(tmp_path, enabled=configured)
    forbidden = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", forbidden)
    monkeypatch.setattr("nettracker.discovery.collector.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.cli.collect_passive", lambda *args, **kwargs: 0)
    assert main(["scan-once", "-c", str(path)]) == 0
    forbidden.assert_not_called()


def test_cli_flag_without_config_is_refused_before_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = config(tmp_path, enabled=False)
    assert main(["scan-once", "-c", str(path), "--resolve-mdns"]) == 1
    assert "scan.mdns_enabled=true" in capsys.readouterr().err
    assert not (tmp_path / "devices.db").exists()


@pytest.mark.parametrize("source", ["cache", "active_arp", "active_nmap", "system_neighbor_cache"])
def test_mdns_persists_and_marks_cycle_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    path = config(tmp_path, active=source != "cache")
    neighbors = [Neighbor("192.168.1.2", "02:11:22:33:44:55")] * 2
    monkeypatch.setattr("nettracker.cli.read_neighbors", lambda _: neighbors)
    if source != "cache":
        result = DiscoveryResult(neighbors, source, source != "active_arp")
        monkeypatch.setattr("nettracker.cli.discover_with_fallback", lambda *a, **k: result)

    def answer(query: dns.message.Message, where: str, **kwargs: object) -> dns.message.Message:
        assert where == "192.168.1.2"
        assert kwargs["timeout"] == 0.5
        response = dns.message.make_response(query)
        response.answer.append(
            dns.rrset.from_text(query.question[0].name, 120, "IN", "PTR", "Phone.Local.")
        )
        return response

    transport = Mock(side_effect=answer)
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", transport)
    monkeypatch.setattr(
        "nettracker.cli.reverse_hostname", Mock(side_effect=AssertionError("DNS forbidden"))
    )
    args = ["scan-once", "-c", str(path), "--resolve-mdns"]
    if source != "cache":
        args += ["--enable-active", "--target", "192.168.1.0/24"]
    assert main(args) == 0
    transport.assert_called_once()
    conn = connect(tmp_path / "devices.db")
    try:
        devices = Repository(conn).list_devices()
        assert len(devices) == 1
        assert devices[0].hostname == "phone.local"
        assert devices[0].status == "to_confirm"
        row = conn.execute("SELECT mode, status, devices_found FROM scans").fetchone()
        assert tuple(row) == ("active", "ok", 1)
    finally:
        conn.close()


@pytest.mark.parametrize("dns_enabled", [False, True])
def test_mdns_timeout_does_not_enable_dns_implicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dns_enabled: bool
) -> None:
    path = config(tmp_path)
    monkeypatch.setattr(
        "nettracker.cli.read_neighbors", lambda _: [Neighbor("192.168.1.2", "00:11:22:33:44:55")]
    )
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", Mock(side_effect=TimeoutError))
    reverse = Mock(return_value="fixture.example")
    monkeypatch.setattr("nettracker.cli.reverse_hostname", reverse)
    args = ["scan-once", "-c", str(path), "--resolve-mdns"]
    if dns_enabled:
        args.append("--resolve-names")
    assert main(args) == 0
    assert reverse.call_count == int(dns_enabled)
    conn = connect(tmp_path / "devices.db")
    try:
        assert Repository(conn).list_devices()[0].hostname == (
            "fixture.example" if dns_enabled else None
        )
    finally:
        conn.close()


def test_out_of_scope_observation_never_reaches_mdns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config(tmp_path)
    monkeypatch.setattr(
        "nettracker.cli.read_neighbors", lambda _: [Neighbor("192.168.2.2", "00:11:22:33:44:55")]
    )
    transport = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr("nettracker.discovery.mdns.dns.query.udp", transport)
    assert main(["scan-once", "-c", str(path), "--resolve-mdns"]) == 1
    transport.assert_not_called()
    conn = connect(tmp_path / "devices.db")
    try:
        assert Repository(conn).list_devices() == []
        assert conn.execute("SELECT status FROM scans").fetchone()[0] == "error"
    finally:
        conn.close()


def test_transport_failure_still_keeps_scoped_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config(tmp_path)
    monkeypatch.setattr(
        "nettracker.cli.read_neighbors", lambda _: [Neighbor("192.168.1.2", "00:11:22:33:44:55")]
    )
    monkeypatch.setattr(
        "nettracker.discovery.mdns.dns.query.udp", Mock(side_effect=PermissionError)
    )
    assert main(["scan-once", "-c", str(path), "--resolve-mdns"]) == 0
    conn = connect(tmp_path / "devices.db")
    try:
        assert Repository(conn).list_devices()[0].hostname is None
    finally:
        conn.close()


def test_mdns_success_skips_opted_in_dns_and_caches_per_ipv4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config(tmp_path)
    monkeypatch.setattr(
        "nettracker.cli.read_neighbors",
        lambda _: [
            Neighbor("192.168.1.2", "00:11:22:33:44:55"),
            Neighbor("192.168.1.2", "02:11:22:33:44:55"),
        ],
    )
    mdns = Mock(return_value="fixture.local")
    dns = Mock(side_effect=AssertionError("DNS should not run after mDNS success"))
    monkeypatch.setattr("nettracker.cli.mdns_hostname", mdns)
    monkeypatch.setattr("nettracker.cli.reverse_hostname", dns)
    assert main(["scan-once", "-c", str(path), "--resolve-mdns", "--resolve-names"]) == 0
    mdns.assert_called_once_with(
        "192.168.1.2", [IPv4Network("192.168.1.0/24")], enabled=True, timeout=0.5
    )
    dns.assert_not_called()
