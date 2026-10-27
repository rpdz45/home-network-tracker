"""Independent discovery-retention authorization and bounded CLI passes on temporary SQLite."""

import sqlite3
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest

from nettracker.config import DiscoveryRetentionSettings
from nettracker.db.discovery_retention import DiscoveryRetentionResult, retain_discovery
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.repository import to_iso
from nettracker.errors import ConfigError, DatabaseError
from nettracker.monitor import loop

from .test_loop_ping_retention import ARGS, NOW, Case
from .test_loop_ping_retention import case as case


@pytest.fixture
def discovery_case(case: Case, monkeypatch: pytest.MonkeyPatch) -> Case:
    repo = MonitoringRepository(case.conn)
    for index in range(6):
        moment = NOW - timedelta(days=2, seconds=index)
        scan = repo.start_scan(mode="passive", started_at=moment)
        repo.add_sighting(
            device_id=1, scan_id=scan, ip="192.168.1.20", online=True, seen_at=moment
        )
        repo.finish_scan(scan, status="ok", finished_at=moment)
    current = repo.start_scan(mode="passive", started_at=NOW)
    repo.finish_scan(current, status="ok", finished_at=NOW)
    for index in range(5):
        moment = NOW - timedelta(days=2, minutes=index)
        problem = repo.start_scan(mode="passive", started_at=moment)
        if index != 4:
            repo.finish_scan(problem, status="error", finished_at=moment)
    boundary = NOW - timedelta(days=1)
    scan = repo.start_scan(mode="passive", started_at=boundary)
    repo.add_sighting(
        device_id=1, scan_id=scan, ip="192.168.1.20", online=True, seen_at=boundary
    )
    repo.finish_scan(scan, status="ok", finished_at=boundary)
    configured = DiscoveryRetentionSettings(enabled=True, keep_days=1, batch_size=2, max_batches=9)
    case.settings = case.settings.model_copy(update={"discovery_retention": configured})
    monkeypatch.setattr("nettracker.config.load_settings", lambda *a, **k: case.settings)
    return case


def old_observations(case: Case) -> int:
    row = case.conn.execute(
        "SELECT COUNT(*) FROM sightings WHERE source='discovery' AND seen_at < ?",
        (to_iso(NOW - timedelta(days=1)),),
    ).fetchone()
    return int(row[0])


def preserved(conn: sqlite3.Connection) -> list[list[tuple[object, ...]]]:
    queries = [
        "SELECT * FROM devices ORDER BY id",
        "SELECT * FROM sightings WHERE source='ping' ORDER BY id",
        "SELECT * FROM monitor_state ORDER BY device_id",
        "SELECT * FROM events ORDER BY id",
        "SELECT * FROM notifications ORDER BY id",
    ]
    return [[tuple(row) for row in conn.execute(query)] for query in queries]


def test_enabled_config_alone_does_not_prune(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    prune = Mock(side_effect=AssertionError("discovery purge requires its own flag"))
    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", prune)
    assert loop.main(ARGS) == 0
    prune.assert_not_called()
    assert old_observations(discovery_case) == 6


def test_ping_authorization_does_not_authorize_discovery(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = Mock(side_effect=AssertionError("must refuse before opening"))
    monkeypatch.setattr("nettracker.db.connect", opened)
    assert loop.main([*ARGS, "--prune-ping", "--prune-discovery"]) == 2
    opened.assert_not_called()
    case.probes.assert_not_called()


def test_cadence_preserves_targets_health_scans_and_ping(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[int] = []
    protected_scans = [
        row[0]
        for row in discovery_case.conn.execute(
            "SELECT id FROM scans WHERE status!='ok' OR started_at=?", (to_iso(NOW),)
        )
    ]

    def checked(
        conn: sqlite3.Connection,
        now: datetime,
        *,
        keep_days: int,
        batch_size: int,
        max_batches: int,
        enabled: bool,
    ) -> DiscoveryRetentionResult:
        assert not conn.in_transaction
        assert (keep_days, batch_size, max_batches, enabled) == (1, 2, 1, True)
        calls.append(discovery_case.probes.call_count)
        repo = MonitoringRepository(conn)
        targets = [repo.target(value) for value in (1, 2)]
        before = preserved(conn)
        result = retain_discovery(
            conn, now, keep_days=keep_days, batch_size=batch_size, max_batches=1, enabled=enabled
        )
        assert preserved(conn) == before
        assert [repo.target(value) for value in (1, 2)] == targets
        assert result.observations <= 2 and result.scans <= 2
        return result

    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", checked)
    args = [*ARGS, "--prune-discovery", "--cycles", "5"]
    args += ["--discovery-prune-every-cycles", "2"]
    assert loop.main(args) == 0
    assert calls == [2, 4]
    assert old_observations(discovery_case) == 2
    remaining = {row[0] for row in discovery_case.conn.execute("SELECT id FROM scans")}
    assert set(protected_scans) <= remaining
    boundary = to_iso(NOW - timedelta(days=1))
    row = discovery_case.conn.execute(
        "SELECT COUNT(*) FROM sightings WHERE source='discovery' AND seen_at=?", (boundary,)
    ).fetchone()
    assert row[0] == 1
    assert "pruned_discovery_observations=4 pruned_scans=4" in capsys.readouterr().out
    assert list(discovery_case.conn.execute("PRAGMA foreign_key_check")) == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--prune-discovery", "--discovery-prune-every-cycles", "0"],
        ["--prune-discovery", "--discovery-prune-every-cycles", "1000001"],
        ["--discovery-prune-every-cycles", "1"],
    ],
)
def test_invalid_cadence_fails_before_loading(
    extra: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    load = Mock(side_effect=AssertionError("must validate before loading"))
    monkeypatch.setattr("nettracker.config.load_settings", load)
    with pytest.raises(SystemExit) as exc:
        loop.main([*ARGS, *extra])
    assert exc.value.code == 2
    load.assert_not_called()


def test_stop_during_ping_purge_skips_discovery(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = Event()
    monkeypatch.setattr(loop, "Event", lambda: stopped)

    def ping(*args: object, **kwargs: object) -> int:
        stopped.set()
        return 0

    discovery = Mock()
    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", ping)
    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", discovery)
    args = [*ARGS, "--prune-ping", "--prune-every-cycles", "1", "--prune-discovery"]
    args += ["--discovery-prune-every-cycles", "1"]
    assert loop.main(args) == 0
    discovery.assert_not_called()
    assert old_observations(discovery_case) == 6


def test_failed_monitoring_skips_discovery(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = Mock(side_effect=ConfigError("fixture"))
    discovery = Mock()
    monkeypatch.setattr("nettracker.monitor.service.monitor_once", monitor)
    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", discovery)
    args = [*ARGS, "--prune-discovery", "--discovery-prune-every-cycles", "1"]
    assert loop.main(args) == 2
    discovery.assert_not_called()
    assert old_observations(discovery_case) == 6


def test_discovery_error_keeps_committed_measurement(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    prune = Mock(side_effect=DatabaseError("fixture"))
    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", prune)
    args = [*ARGS, "--prune-discovery", "--discovery-prune-every-cycles", "1"]
    assert loop.main(args) == 2
    prune.assert_called_once()
    assert discovery_case.probes.call_count == 1
    row = discovery_case.conn.execute(
        "SELECT COUNT(*) FROM sightings WHERE source='ping' AND seen_at=?", (to_iso(NOW),)
    ).fetchone()
    assert row[0] == 1
    assert old_observations(discovery_case) == 6


def test_both_purges_have_independent_cadences(
    discovery_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []

    def ping(*args: object, **kwargs: object) -> int:
        calls.append(("ping", discovery_case.probes.call_count))
        return 0

    def discovery(*args: object, **kwargs: object) -> DiscoveryRetentionResult:
        calls.append(("discovery", discovery_case.probes.call_count))
        return DiscoveryRetentionResult(0, 0, applied=True)

    monkeypatch.setattr("nettracker.db.retention.prune_ping_samples", ping)
    monkeypatch.setattr("nettracker.db.discovery_retention.retain_discovery", discovery)
    args = [*ARGS, "--prune-ping", "--prune-every-cycles", "2", "--cycles", "5"]
    args += ["--prune-discovery", "--discovery-prune-every-cycles", "3"]
    assert loop.main(args) == 0
    assert calls == [("ping", 2), ("discovery", 3), ("ping", 4)]
