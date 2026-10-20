"""Exercise CLI, fallback selection and SQLite with fake ARP and nmap only."""

from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect
from nettracker.discovery.arp import ActiveDiscoveryError
from nettracker.discovery.nmap import discover_nmap
from nettracker.discovery.passive import Neighbor

XML = (
    '<nmaprun><host><status state="up"/>'
    '<address addr="192.168.1.2" addrtype="ipv4"/>'
    '<address addr="02:11:22:33:44:55" addrtype="mac"/></host>'
    '<runstats><finished exit="success"/></runstats></nmaprun>'
)


def test_cli_fallback_is_active_in_sqlite_and_receives_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    path = tmp_path / "devices.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{path.as_posix()}"\n'
        '[scan]\nmode = "active"\nnmap_fallback = true\nnmap_timeout_seconds = 12\n',
        encoding="utf-8",
    )
    calls: list[tuple[str, float]] = []

    def unavailable(*_args: object, **_kwargs: object) -> list[Neighbor]:
        raise ActiveDiscoveryError("simulated missing privileges")

    def fake_runner(target: str, timeout: float) -> str:
        calls.append((target, timeout))
        return XML

    def fake_nmap(
        target: str, subnets: list[IPv4Network], *, enabled: bool, timeout: float
    ) -> list[Neighbor]:
        return discover_nmap(target, subnets, enabled=enabled, timeout=timeout, runner=fake_runner)

    monkeypatch.setattr("nettracker.discovery.strategy.discover_arp", unavailable)
    monkeypatch.setattr("nettracker.discovery.strategy.discover_nmap", fake_nmap)
    monkeypatch.setattr(
        "nettracker.discovery.nmap.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("unexpected process invocation"),
    )
    assert (
        main(
            [
                "scan-once",
                "--config",
                str(config),
                "--enable-active",
                "--target",
                "192.168.1.0/24",
            ]
        )
        == 0
    )
    assert calls == [("192.168.1.0/24", 12.0)]
    output = capsys.readouterr().out
    assert "Degraded mode: nmap host discovery fallback (active)" in output
    assert "1 observation(s) from active_nmap" in output
    conn = connect(path)
    try:
        row = conn.execute("SELECT mode, status, devices_found FROM scans").fetchone()
        assert tuple(row) == ("active", "ok", 1)
        device = Repository(conn).get_device_by_mac("02:11:22:33:44:55")
        assert device is not None
        assert device.status == "to_confirm"
    finally:
        conn.close()


def test_passive_cli_with_nmap_opt_in_never_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "passive.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\n'
        f'database_path = "{database.as_posix()}"\n'
        "[scan]\nnmap_fallback = true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nettracker.cli.discover_with_fallback",
        lambda *_args, **_kwargs: pytest.fail("active discovery called"),
    )
    monkeypatch.setattr("nettracker.cli.collect_passive", lambda *_args, **_kwargs: 0)
    assert main(["scan-once", "--config", str(config)]) == 0
