"""CLI IEEE vendor file tests use synthetic local data and no neighbor lookup."""

from pathlib import Path

import pytest

from nettracker.cli import main


def test_cli_loads_local_ieee_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "x.db"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    oui = tmp_path / "oui.csv"
    oui.write_text(
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,001A2B,Example Devices Inc.,Nowhere\n",
        encoding="utf-8",
    )
    seen: list[dict[str, str]] = []

    def fake_collect(repo: object, subnets: object, *, vendors: dict[str, str]) -> int:
        seen.append(vendors)
        return 0

    monkeypatch.setattr("nettracker.cli.collect_passive", fake_collect)
    assert main(["scan-once", "--config", str(config), "--oui-file", str(oui)]) == 0
    assert seen == [{"001A2B": "Example Devices Inc."}]


def test_invalid_vendor_file_refused_before_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "x.db"
    config = tmp_path / "config.toml"
    config.write_text(
        f'allowed_subnets = ["192.168.1.0/24"]\ndatabase_path = "{database.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nettracker.cli.collect_passive", lambda *args, **kwargs: pytest.fail("called")
    )
    assert (
        main(["scan-once", "--config", str(config), "--oui-file", str(tmp_path / "missing.csv")])
        == 1
    )
    assert "cannot load IEEE vendor file" in capsys.readouterr().err
    assert not database.exists()
