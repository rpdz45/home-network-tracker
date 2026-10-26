"""Disk-backed monitoring recovery with fake probes and real SQLite connections."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.discovery_retention import retain_discovery
from nettracker.db.monitoring import MonitoringRepository
from nettracker.errors import DatabaseError
from nettracker.monitor.ping import PingResult
from nettracker.monitor.service import monitor_once

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
IP = "192.168.1.20"
OTHER_IP = "192.168.1.21"
NEW_IP = "192.168.1.22"


def settings(path: Path) -> Settings:
    return Settings.model_validate(
        {
            "allowed_subnets": ["192.168.1.0/24"],
            "database_path": str(path),
            "monitor": {"enabled": True, "max_observation_age_seconds": 60},
        }
    )


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real ping backend is forbidden")

    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    path = tmp_path / "recovery.db"
    with closing(connect(path, timeout=0.01)) as conn:
        migrate(conn)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        repo = MonitoringRepository(conn)
        before = T0 - timedelta(days=2)
        for mac, ip in (("02:00:00:00:00:01", IP), ("02:00:00:00:00:02", OTHER_IP)):
            device = repo.upsert_device(mac, seen_at=before)
            repo.add_sighting(device_id=device.id, ip=ip, online=True, seen_at=before)
            repo.upsert_device(mac, seen_at=T0)
            repo.add_sighting(device_id=device.id, ip=ip, online=True, seen_at=T0)
        repo.set_status(1, "to_confirm")
    return path


def test_reopen_preserves_transitions_trust_and_idempotence(database: Path) -> None:
    outcomes = (PingResult(1, 1, 1.0), PingResult(1, 0, None), PingResult(1, 1, 1.0))
    for index, outcome in enumerate(outcomes):
        moment = T0 + timedelta(seconds=index)
        with closing(connect(database, timeout=0.01)) as conn:
            repo = MonitoringRepository(conn)
            target = repo.target(1)
            count = monitor_once(
                repo,
                settings(database),
                [1],
                enabled=True,
                probe=Mock(return_value=outcome),
                clock=Mock(return_value=moment),
            )
            assert count == 1
            if index == 1:
                retained = retain_discovery(conn, moment, keep_days=1, enabled=True)
                assert retained.observations == 2
                assert repo.target(1) == target
            assert not conn.in_transaction
    with closing(connect(database, timeout=0.01)) as conn:
        repo = MonitoringRepository(conn)
        kinds = [row[0] for row in conn.execute("SELECT kind FROM events ORDER BY id")]
        assert kinds == ["offline", "online"]
        device = repo.get_device(1)
        assert device is not None and device.status == "to_confirm"
        assert device.last_seen == T0.isoformat(timespec="microseconds")
        repeated = monitor_once(
            repo,
            settings(database),
            [1],
            enabled=True,
            probe=Mock(return_value=outcomes[-1]),
            clock=lambda: T0 + timedelta(seconds=2),
        )
        assert repeated == 0
        assert conn.execute("SELECT COUNT(*) FROM sightings WHERE source='ping'").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_locked_cycle_can_be_retried_after_reopen(database: Path) -> None:
    with closing(connect(database, timeout=0.01)) as conn:
        initial = monitor_once(
            MonitoringRepository(conn),
            settings(database),
            [1, 2],
            enabled=True,
            probe=Mock(return_value=PingResult(1, 1, 1.0)),
            clock=lambda: T0,
        )
        assert initial == 2
    with (
        closing(connect(database, timeout=0.01)) as conn,
        closing(connect(database, timeout=0.01)) as blocker,
    ):
        before = tuple(conn.iterdump())
        probe = Mock(return_value=PingResult(1, 0, None))
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(DatabaseError, match="locked"):
                monitor_once(
                    MonitoringRepository(conn),
                    settings(database),
                    [1, 2],
                    enabled=True,
                    probe=probe,
                    clock=lambda: T0 + timedelta(seconds=1),
                )
            assert probe.call_count == 2
            assert not conn.in_transaction
            assert blocker.in_transaction
            assert tuple(conn.iterdump()) == before
        finally:
            blocker.execute("ROLLBACK")
    with closing(connect(database, timeout=0.01)) as conn:
        for expected in (2, 0):
            saved = monitor_once(
                MonitoringRepository(conn),
                settings(database),
                [1, 2],
                enabled=True,
                probe=Mock(return_value=PingResult(1, 0, None)),
                clock=lambda: T0 + timedelta(seconds=1),
            )
            assert saved == expected
        assert conn.execute("SELECT COUNT(*) FROM sightings WHERE source='ping'").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='offline'").fetchone()[0] == 2
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_other_connection_discovery_survives_failed_monitor_batch(database: Path) -> None:
    with (
        closing(connect(database, timeout=0.01)) as conn,
        closing(connect(database, timeout=0.01)) as writer,
    ):
        repo = MonitoringRepository(conn)
        observed: list[str] = []

        def changed(ip: str) -> PingResult:
            assert not conn.in_transaction
            observed.append(ip)
            if ip == OTHER_IP:
                MonitoringRepository(writer).add_sighting(
                    device_id=2,
                    ip=NEW_IP,
                    online=True,
                    seen_at=T0 + timedelta(seconds=1),
                )
            return PingResult(1, 1, 1.0)

        with pytest.raises(DatabaseError, match="changed"):
            monitor_once(
                repo,
                settings(database),
                [1, 2],
                enabled=True,
                probe=changed,
                clock=lambda: T0 + timedelta(seconds=2),
            )
        assert observed == [IP, OTHER_IP]
        assert not conn.in_transaction
    with closing(connect(database, timeout=0.01)) as conn:
        repo = MonitoringRepository(conn)
        assert repo.target(2).ip == NEW_IP
        assert conn.execute("SELECT COUNT(*) FROM sightings WHERE source='ping'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM monitor_state").fetchone()[0] == 0
        probe = Mock(return_value=PingResult(1, 1, 1.0))
        saved = monitor_once(
            repo,
            settings(database),
            [1, 2],
            enabled=True,
            probe=probe,
            clock=lambda: T0 + timedelta(seconds=3),
        )
        assert saved == 2
        assert [call.args[0] for call in probe.call_args_list] == [IP, NEW_IP]
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
