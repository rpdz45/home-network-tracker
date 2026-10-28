"""Local registry loading uses synthetic files and never downloads data."""

from datetime import UTC, datetime
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.discovery.oui_registry import load_local_registry, parse_ma_l_csv

CSV = "Registry,Assignment,Organization Name\nMA-L,001A2B,Example Devices Inc.\n"


def test_missing_registry_is_optional(tmp_path: Path) -> None:
    assert load_local_registry(tmp_path / "missing.csv") is None


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_registry_accepts_utf8_and_bom(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "oui.csv"
    path.write_text(CSV, encoding=encoding)
    assert load_local_registry(path) == {"001A2B": "Example Devices Inc."}


def test_default_path_is_relative_to_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data/oui/oui.csv"
    path.parent.mkdir(parents=True)
    path.write_text(CSV, encoding="utf-8")
    assert load_local_registry() == {"001A2B": "Example Devices Inc."}


@pytest.mark.parametrize(
    "payload",
    [
        b"wrong,columns\nvalue,data\n",
        b"\xff",
        b"Registry,Assignment,Organization Name\n",
        b"Registry,Assignment,Organization Name\nMA-L,001A2B,Private\n",
    ],
)
def test_unusable_registry_is_ignored(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "oui.csv"
    path.write_bytes(payload)
    assert load_local_registry(path) is None


def test_registry_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "oui.csv"
    path.write_bytes(b"x" * 9)
    monkeypatch.setattr("nettracker.discovery.oui_registry.MAX_REGISTRY_BYTES", 8)
    assert load_local_registry(path) is None


def test_directory_is_not_a_registry(tmp_path: Path) -> None:
    assert load_local_registry(tmp_path) is None


def test_parser_compatibility() -> None:
    assert parse_ma_l_csv(CSV) == {"001A2B": "Example Devices Inc."}
    with pytest.raises(ValueError, match="header"):
        parse_ma_l_csv("wrong,columns\n")


@pytest.mark.parametrize("explicit_empty", [False, True])
def test_collector_autoload_and_explicit_mapping_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit_empty: bool
) -> None:
    from nettracker.db import Repository, connect, migrate
    from nettracker.discovery.collector import collect_passive
    from nettracker.discovery.passive import Neighbor

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data/oui/oui.csv"
    path.parent.mkdir(parents=True)
    path.write_text(CSV + "MA-L,021A2B,Must Not Identify\n", encoding="utf-8")
    conn = connect(tmp_path / "registry.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        count = collect_passive(
            repo,
            [IPv4Network("192.168.1.0/24")],
            reader=lambda _: [
                Neighbor("192.168.1.20", "00:1a:2b:33:44:55"),
                Neighbor("192.168.1.21", "02:1a:2b:33:44:55"),
            ],
            clock=lambda: datetime(2026, 10, 28, tzinfo=UTC),
            vendors={} if explicit_empty else None,
        )
        public = repo.get_device_by_mac("00:1a:2b:33:44:55")
        private = repo.get_device_by_mac("02:1a:2b:33:44:55")
        assert count == 2
        assert public is not None and private is not None
        assert public.vendor == (None if explicit_empty else "Example Devices Inc.")
        assert private.vendor is None
        assert public.status == "unknown"
        assert private.status == "to_confirm"
    finally:
        conn.close()
