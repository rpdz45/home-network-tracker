"""Active CLI tests use a simulated discovery result; no packets are sent."""

from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.discovery.strategy import DiscoveryResult


def test_active_requires_two_explicit_opt_ins_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "devices.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n'
        '[scan]\nmode = "active"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nettracker.cli.discover_with_fallback", lambda *args, **kwargs: pytest.fail("probed")
    )
    assert main(["scan-once", "--config", str(config)]) == 1
    assert main(["scan-once", "--config", str(config), "--enable-active"]) == 1
    assert not database.exists()


@pytest.mark.parametrize("degraded", [False, True])
def test_active_and_fallback_record_correct_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    degraded: bool,
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "devices.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n'
        '[scan]\nmode = "active"\n',
        encoding="utf-8",
    )
    source = "system_neighbor_cache" if degraded else "active_arp"
    monkeypatch.setattr(
        "nettracker.cli.discover_with_fallback",
        lambda *args, **kwargs: DiscoveryResult([], source, degraded),
    )
    modes: list[str] = []

    def fake_collect(repo: object, subnets: object, *, mode: str, **kwargs: object) -> int:
        modes.append(mode)
        return 0

    monkeypatch.setattr("nettracker.cli.collect_observations", fake_collect)
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
    assert modes == ["passive" if degraded else "active"]
    assert ("Degraded mode" in capsys.readouterr().out) == degraded
