"""Persist explicit trust only for observed, scoped MACs; all readers are simulated."""

from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from nettracker.cli import main
from nettracker.db import Repository, connect, migrate
from nettracker.db.repository import DeviceStatus
from nettracker.discovery.collector import ScanMode, collect_observations, collect_passive
from nettracker.discovery.passive import Neighbor
from nettracker.discovery.scope import ScopeError
from nettracker.discovery.strategy import DiscoveryResult

ALLOWED = [IPv4Network("192.168.1.0/24")]
NOW = datetime(2026, 1, 1, tzinfo=UTC)
MAC = "02:aa:bb:cc:dd:ee"
OTHER = "00:11:22:33:44:66"


@pytest.mark.parametrize("mode", ["passive", "active"])
@pytest.mark.parametrize("mac", [MAC, OTHER])
def test_new_approved_device_has_no_unknown_event(tmp_path: Path, mode: ScanMode, mac: str) -> None:
    conn = connect(tmp_path / "known.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        for _ in range(2):
            assert (
                collect_observations(
                    repo,
                    ALLOWED,
                    mode=mode,
                    reader=lambda _: [Neighbor("192.168.1.2", mac)],
                    clock=lambda: NOW,
                    known_devices=[mac.upper().replace(":", "-")],
                )
                == 1
            )
        device = repo.get_device_by_mac(mac)
        assert device is not None
        assert device.status == "known"
        assert device.is_randomized_mac == (mac == MAC)
        assert repo.list_events() == []
        assert len(repo.list_devices()) == 1
        assert conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("status", ["unknown", "to_confirm", "known", "ignored"])
def test_existing_status_priority(tmp_path: Path, status: DeviceStatus) -> None:
    conn = connect(tmp_path / "existing.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        device = repo.upsert_device(MAC, seen_at=NOW)
        repo.set_status(device.id, status)
        collect_passive(
            repo,
            ALLOWED,
            known_devices=[MAC],
            clock=lambda: NOW,
            reader=lambda _: [Neighbor("192.168.1.2", MAC)],
        )
        saved = repo.get_device(device.id)
        assert saved is not None
        assert saved.status == ("ignored" if status == "ignored" else "known")
        assert repo.list_events() == []
    finally:
        conn.close()


def test_merge_is_never_undone(tmp_path: Path) -> None:
    conn = connect(tmp_path / "merged.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        target = repo.upsert_device(OTHER, seen_at=NOW)
        device = repo.upsert_device(MAC, seen_at=NOW)
        repo.set_status(device.id, "to_confirm")
        conn.execute("UPDATE devices SET merged_into = ? WHERE id = ?", (target.id, device.id))
        collect_passive(
            repo,
            ALLOWED,
            known_devices=[MAC],
            clock=lambda: NOW,
            reader=lambda _: [Neighbor("192.168.1.2", MAC)],
            hostname_lookup=lambda _: "fictional.local",
        )
        saved = repo.get_device(device.id)
        assert saved is not None
        assert saved.merged_into == target.id
        assert saved.status == "to_confirm"
        assert repo.list_events() == []
    finally:
        conn.close()


def test_no_precreation_and_no_trust_by_ip_or_hostname(tmp_path: Path) -> None:
    conn = connect(tmp_path / "unseen.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        collect_passive(repo, ALLOWED, known_devices=[MAC], reader=lambda _: [])
        assert repo.list_devices() == []
        collect_passive(
            repo,
            ALLOWED,
            known_devices=[MAC],
            clock=lambda: NOW,
            reader=lambda _: [Neighbor("192.168.1.2", OTHER)],
            hostname_lookup=lambda _: "fictional.local",
        )
        device = repo.get_device_by_mac(OTHER)
        assert device is not None
        assert device.status == "unknown"
        assert repo.get_device_by_mac(MAC) is None
        assert len(repo.list_events(kind="new_device")) == 1
    finally:
        conn.close()


def test_removal_and_reopen_do_not_revoke_persisted_trust(tmp_path: Path) -> None:
    path = tmp_path / "reopen.db"
    for allowlist in ([MAC], []):
        conn = connect(path)
        try:
            migrate(conn)
            repo = Repository(conn)
            collect_passive(
                repo,
                ALLOWED,
                known_devices=allowlist,
                clock=lambda: NOW,
                reader=lambda _: [Neighbor("192.168.1.2", MAC)],
            )
            device = repo.get_device_by_mac(MAC)
            assert device is not None
            assert device.status == "known"
            assert repo.list_events() == []
        finally:
            conn.close()


def test_allowlist_does_not_bypass_scope_and_rolls_back(tmp_path: Path) -> None:
    conn = connect(tmp_path / "scope.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        with pytest.raises(ScopeError):
            collect_passive(
                repo,
                ALLOWED,
                known_devices=[MAC, OTHER],
                clock=lambda: NOW,
                reader=lambda _: [Neighbor("192.168.1.2", OTHER), Neighbor("8.8.8.8", MAC)],
            )
        assert repo.list_devices() == []
        assert repo.list_events() == []
        assert conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM scans").fetchone()[0] == "error"
    finally:
        conn.close()


def test_invalid_allowlist_is_refused_before_reader(tmp_path: Path) -> None:
    conn = connect(tmp_path / "invalid.db")
    try:
        migrate(conn)
        with pytest.raises(ValueError):
            collect_passive(
                Repository(conn),
                ALLOWED,
                known_devices=["invalid"],
                reader=lambda _: pytest.fail("reader called with invalid configuration"),
            )
        assert conn.execute("SELECT count(*) FROM scans").fetchone()[0] == 0
    finally:
        conn.close()


def test_allowlisted_random_mac_does_not_suggest_a_merge(tmp_path: Path) -> None:
    conn = connect(tmp_path / "suggestions.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        older = repo.upsert_device(OTHER, seen_at=NOW, hostname="fictional.local")
        repo.set_status(older.id, "known")
        collect_passive(
            repo,
            ALLOWED,
            known_devices=[MAC],
            clock=lambda: NOW + timedelta(hours=1),
            reader=lambda _: [Neighbor("192.168.1.2", MAC)],
            hostname_lookup=lambda _: "fictional.local",
        )
        assert repo.list_events() == []
        device = repo.get_device_by_mac(MAC)
        assert device is not None and device.status == "known" and device.merged_into is None
    finally:
        conn.close()


@pytest.mark.parametrize("resolve_names", [False, True])
@pytest.mark.parametrize(
    "source", ["passive", "active_arp", "active_nmap", "system_neighbor_cache"]
)
def test_cli_passes_allowlist_to_all_discovery_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, resolve_names: bool
) -> None:
    config = tmp_path / "config.toml"
    database = tmp_path / "cli.db"
    active = source != "passive"
    config.write_text(
        'allowed_subnets = ["192.168.1.0/24"]\nknown_devices = ["02-AA-BB-CC-DD-EE"]\n'
        f'database_path = "{database.as_posix()}"\n'
        + ('[scan]\nmode = "active"\n' if active else ""),
        encoding="utf-8",
    )
    oui = tmp_path / "oui.csv"
    oui.write_text(
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,001122,Fictional Devices,Nowhere\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("nettracker.cli.reverse_hostname", lambda *a, **k: "fictional.local")
    entries = [Neighbor("192.168.1.2", MAC)]
    if active:
        result = DiscoveryResult(entries, source, source != "active_arp")
        monkeypatch.setattr("nettracker.cli.discover_with_fallback", lambda *a, **k: result)
    else:

        def fake_passive(repo: Repository, subnets: list[IPv4Network], **kwargs: object) -> int:
            assert kwargs["known_devices"] == (MAC,)
            assert (kwargs["hostname_lookup"] is not None) == resolve_names
            assert kwargs["vendors"] == {"001122": "Fictional Devices"}
            return collect_passive(repo, subnets, reader=lambda _: entries, known_devices=[MAC])

        monkeypatch.setattr("nettracker.cli.collect_passive", fake_passive)
    args = ["scan-once", "--config", str(config), "--oui-file", str(oui)]
    if resolve_names:
        args.append("--resolve-names")
    if active:
        args += ["--enable-active", "--target", "192.168.1.0/24"]
    assert main(args) == 0
    conn = connect(database)
    try:
        repo = Repository(conn)
        device = repo.get_device_by_mac(MAC)
        assert device is not None and device.status == "known"
        assert repo.list_events() == []
        mode = "active" if source in ("active_arp", "active_nmap") else "passive"
        assert conn.execute("SELECT mode FROM scans").fetchone()[0] == mode
    finally:
        conn.close()


def test_mac_formats_deduplicate_before_sighting(tmp_path: Path) -> None:
    conn = connect(tmp_path / "formats.db")
    try:
        migrate(conn)
        repo = Repository(conn)
        count = collect_passive(
            repo,
            ALLOWED,
            known_devices=[MAC],
            reader=lambda _: [
                Neighbor("192.168.1.2", MAC.upper().replace(":", "-")),
                Neighbor("192.168.1.2", MAC),
            ],
        )
        assert count == 1
        device = repo.get_device_by_mac(MAC)
        assert device is not None and device.status == "known"
        assert conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == 1
    finally:
        conn.close()
