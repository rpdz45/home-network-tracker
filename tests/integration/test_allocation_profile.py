"""Optional snapshot integration; real profiling on tiny disposable scenarios only."""

import json
import tracemalloc
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest

from nettracker import resource_profile


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("real cache, ping and user configuration are forbidden")

    monkeypatch.setattr("nettracker.monitor.refresh.read_neighbors", forbidden)
    monkeypatch.setattr("nettracker.monitor.service.probe_ping", forbidden)
    monkeypatch.setattr("nettracker.config.load_settings", forbidden)
    monkeypatch.setattr(
        resource_profile, "TemporaryDirectory", partial(TemporaryDirectory, dir=tmp_path)
    )


def test_default_mode_keeps_schema_and_never_takes_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = Mock(side_effect=AssertionError("snapshots require explicit opt-in"))
    monkeypatch.setattr(tracemalloc, "take_snapshot", snapshots)
    report = resource_profile.profile_resources(cycles=1, warmup=1)
    snapshots.assert_not_called()
    assert all("allocations" not in asdict(window) for window in report.windows)
    assert not tracemalloc.is_tracing()


def test_optional_details_are_bounded_and_redacted(tmp_path: Path) -> None:
    report = resource_profile.profile_resources(cycles=2, warmup=1, allocation_details=True)
    assert len(report.windows) == 2
    for window in report.windows:
        assert isinstance(window, resource_profile.AllocationWindow)
        assert len(window.allocations.entries) <= 10
        for entry in window.allocations.entries:
            assert entry.source.startswith("nettracker/")
            assert "\\" not in entry.source and ":" not in entry.source
            assert not Path(entry.source).is_absolute()
            assert entry.line > 0
    encoded = json.dumps(asdict(report))
    assert json.dumps(str(tmp_path))[1:-1] not in encoded
    package = str(Path(resource_profile.__file__).resolve().parent)
    assert json.dumps(package)[1:-1] not in encoded
    assert not tracemalloc.is_tracing()
    assert list(tmp_path.iterdir()) == []


def test_cli_opt_in_includes_allocation_summaries(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--cycles", "1", "--warmup", "1", "--allocation-details"]
    assert resource_profile.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["simulated"] is True
    assert all("allocations" in window for window in report["windows"])
