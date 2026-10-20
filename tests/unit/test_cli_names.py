"""CLI name resolution tests use simulated observations and DNS."""

from collections.abc import Mapping
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect
from nettracker.discovery.collector import HostnameLookup, collect_passive
from nettracker.discovery.passive import Neighbor


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_names_are_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in (
        "NETTRACKER_CONFIG",
        "NETTRACKER_DATABASE_PATH",
        "NETTRACKER_API_TOKEN",
        "NETTRACKER_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "config.toml"
    database = tmp_path / "devices.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    calls: list[str] = []
    expected_scope = [IPv4Network("192.168.1.0/24")]

    def fake_reverse(ip: str, subnets: list[IPv4Network], *, enabled: bool) -> str:
        assert enabled
        assert subnets == expected_scope
        calls.append(ip)
        return "fixture.example"

    def fake_reader(subnets: list[IPv4Network]) -> list[Neighbor]:
        assert subnets == expected_scope
        return [Neighbor("192.168.1.2", "00:11:22:33:44:55")]

    def fake_collect(
        repo: Repository,
        subnets: list[IPv4Network],
        *,
        vendors: Mapping[str, str] | None = None,
        hostname_lookup: HostnameLookup | None = None,
    ) -> int:
        assert (hostname_lookup is not None) == enabled
        return collect_passive(
            repo,
            subnets,
            reader=fake_reader,
            vendors=vendors,
            hostname_lookup=hostname_lookup,
        )

    monkeypatch.setattr("nettracker.cli.reverse_hostname", fake_reverse)
    monkeypatch.setattr("nettracker.cli.collect_passive", fake_collect)
    args = ["scan-once", "--config", str(config)]
    if enabled:
        args.append("--resolve-names")
    assert main(args) == 0
    assert calls == (["192.168.1.2"] if enabled else [])
    conn = connect(database)
    try:
        hostname = Repository(conn).list_devices()[0].hostname
        assert hostname == ("fixture.example" if enabled else None)
    finally:
        conn.close()
