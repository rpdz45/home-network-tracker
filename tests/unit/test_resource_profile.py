"""Small offline resource-profile contracts; no timing or leak threshold is asserted."""

import json
import tracemalloc
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest

from nettracker import resource_profile
from nettracker.errors import ConfigError, DatabaseError


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real network/cache backends and user configuration are forbidden")

    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.config.load_settings", forbidden)
    monkeypatch.setattr(
        resource_profile, "TemporaryDirectory", partial(TemporaryDirectory, dir=tmp_path)
    )


def test_two_windows_and_temporary_cleanup(tmp_path: Path) -> None:
    report = resource_profile.profile_resources(cycles=3, warmup=2)
    assert report.simulated
    assert report.memory_scope == "tracemalloc-python-not-rss"
    assert len(report.windows) == 2
    assert [window.discovery_rows for window in report.windows] == [5, 8]
    assert [window.ping_rows for window in report.windows] == [5, 8]
    assert [window.scans for window in report.windows] == [5, 8]
    for window in report.windows:
        assert window.cycles == 3
        assert window.wall_seconds >= 0 and window.cpu_seconds >= 0
        assert window.python_delta_bytes == window.python_after_bytes - window.python_before_bytes
        assert window.database_bytes > 0 and window.wal_bytes >= 0
    assert not tracemalloc.is_tracing()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [0, -1, True, 5001])
def test_invalid_limits_fail_before_temporary_directory(
    value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = Mock()
    monkeypatch.setattr(resource_profile, "TemporaryDirectory", directory)
    with pytest.raises(ConfigError):
        resource_profile.profile_resources(cycles=value)
    directory.assert_not_called()


def test_existing_tracer_is_not_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    start = Mock()
    stop = Mock()
    monkeypatch.setattr(resource_profile.tracemalloc, "is_tracing", lambda: True)
    monkeypatch.setattr(resource_profile.tracemalloc, "start", start)
    monkeypatch.setattr(resource_profile.tracemalloc, "stop", stop)
    with pytest.raises(ConfigError, match="existing"):
        resource_profile.profile_resources(cycles=1, warmup=1)
    start.assert_not_called()
    stop.assert_not_called()


def test_failed_open_cleans_trace_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resource_profile, "connect", Mock(side_effect=DatabaseError("fixture")))
    with pytest.raises(DatabaseError):
        resource_profile.profile_resources(cycles=1, warmup=1)
    assert not tracemalloc.is_tracing()
    assert list(tmp_path.iterdir()) == []


def test_cli_emits_explicitly_simulated_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert resource_profile.main(["--cycles", "1", "--warmup", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["simulated"] is True
    assert data["memory_scope"] == "tracemalloc-python-not-rss"
    assert len(data["windows"]) == 2
