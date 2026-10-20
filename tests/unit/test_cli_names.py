"""CLI name resolution is explicit and tested without DNS or neighbor-cache access."""

from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect
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
        'allowed_subnets = ["192.168.1.0/24"]\n'
        f'database_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_reverse(ip: str, subnets: object, *, enabled: bool) -> str:
        assert enabled
        calls.append(ip)
        return "fixture.example"

    def fake_command(argv: list[str], timeout: float) -> str:
        return "192.168.1.2 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE"

    def fake_reader(subnets: object) -> list[Neighbor]:
        return [Neighbor("192.168.1.2", "00:11:22:33:44:55")]

    monkeypatch.setattr("nettracker.cli.reverse_hostname", fake_reverse)
    monkeypatch.setattr("nettracker.discovery.passive.subprocess.run", pytest.fail)
    from nettracker.discovery.collector import collect_passive

    def fake_collect(repo: Repository, subnets: object, **kwargs: object) -> int:
        return collect_passive(
            repo,
            [__import__("ipaddress").IPv4Network("192.168.1.0/24")],
            reader=fake_reader,
            **kwargs,
        )

    monkeypatch.setattr("nettracker.cli.collect_passive", fake_collect)
    args = ["scan-once", "--config", str(config)]
    if enabled:
        args.append("--resolve-names")
    assert main(args) == 0
    assert calls == (["192.168.1.2"] if enabled else [])
    conn = connect(database)
    try:
        assert Repository(conn).list_devices()[0].hostname == (
            "fixture.example" if enabled else None
        )
    finally:
        conn.close()
