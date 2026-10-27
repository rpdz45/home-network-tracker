"""Bounded offline series; no leak, timing or RSS threshold is asserted."""

import json
import tracemalloc
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest

from nettracker import resource_profile
from nettracker.errors import ConfigError


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real backends and user configuration are forbidden")

    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.config.load_settings", forbidden)
    monkeypatch.setattr(
        resource_profile, "TemporaryDirectory", partial(TemporaryDirectory, dir=tmp_path)
    )


@pytest.mark.parametrize("count", [1, 3, 10])
@pytest.mark.parametrize("details", [False, True])
def test_consecutive_series_and_cleanup(tmp_path: Path, count: int, details: bool) -> None:
    report = resource_profile.profile_resources(
        cycles=1, warmup=1, window_count=count, allocation_details=details
    )
    assert len(report.windows) == count
    assert [window.scans for window in report.windows] == list(range(2, count + 2))
    previous_after = None
    for window in report.windows:
        assert isinstance(window, resource_profile.SeriesWindow)
        expected = None if previous_after is None else window.python_before_bytes - previous_after
        assert window.python_between_windows_delta_bytes == expected
        assert window.python_delta_bytes == window.python_after_bytes - window.python_before_bytes
        if details:
            assert isinstance(window, resource_profile.AllocationSeriesWindow)
            assert len(window.allocations.entries) <= 10
        else:
            assert "allocations" not in asdict(window)
        previous_after = window.python_after_bytes
    encoded = json.dumps(asdict(report))
    assert json.dumps(str(tmp_path))[1:-1] not in encoded
    package = str(Path(resource_profile.__file__).resolve().parent)
    assert json.dumps(package)[1:-1] not in encoded
    assert not tracemalloc.is_tracing()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [0, -1, 11, True, 1.5, "3", None])
def test_invalid_window_count_has_no_side_effects(
    value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = Mock()
    start = Mock()
    monkeypatch.setattr(resource_profile, "TemporaryDirectory", directory)
    monkeypatch.setattr(tracemalloc, "start", start)
    with pytest.raises(ConfigError, match="window_count"):
        resource_profile.profile_resources(cycles=1, warmup=1, window_count=value)
    directory.assert_not_called()
    start.assert_not_called()


def test_default_two_windows_keep_existing_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshots = Mock(side_effect=AssertionError("snapshots require opt-in"))
    monkeypatch.setattr(tracemalloc, "take_snapshot", snapshots)
    report = resource_profile.profile_resources(cycles=1, warmup=1)
    assert len(report.windows) == 2
    for window in report.windows:
        assert "python_between_windows_delta_bytes" not in asdict(window)
        assert "allocations" not in asdict(window)
    snapshots.assert_not_called()


def test_series_cli(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--cycles", "1", "--warmup", "1", "--windows", "3", "--allocation-details"]
    assert resource_profile.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["windows"]) == 3
    assert report["simulated"] is True
    assert report["windows"][0]["python_between_windows_delta_bytes"] is None
    assert all("allocations" in window for window in report["windows"])
