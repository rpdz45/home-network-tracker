"""Offline resource measurements on synthetic monitoring and a disposable SQLite file."""

import argparse
import gc
import json
import sqlite3
import sys
import tracemalloc
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter, process_time

from nettracker.config import Settings
from nettracker.db import connect, migrate
from nettracker.db.discovery_retention import retain_discovery
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.retention import cutoff_for, prune_ping_samples
from nettracker.discovery.passive import Neighbor
from nettracker.errors import ConfigError, DatabaseError, NetTrackerError
from nettracker.monitor.loop import run_periodic
from nettracker.monitor.ping import PingResult
from nettracker.monitor.refresh import refresh_selected
from nettracker.monitor.service import monitor_once

START = datetime(2026, 10, 26, 12, tzinfo=UTC)
MAC = "02:00:00:00:00:01"
IP = "192.168.1.20"


@dataclass(frozen=True)
class Window:
    cycles: int
    wall_seconds: float
    cpu_seconds: float
    python_before_bytes: int
    python_after_bytes: int
    python_delta_bytes: int
    python_peak_bytes: int
    discovery_rows: int
    ping_rows: int
    scans: int
    database_bytes: int
    wal_bytes: int


@dataclass(frozen=True)
class Profile:
    warmup_cycles: int
    cycles_per_window: int
    python_version: str
    platform: str
    windows: tuple[Window, ...]
    simulated: bool = True
    memory_scope: str = "tracemalloc-python-not-rss"


def _prune(conn: sqlite3.Connection, moment: datetime) -> None:
    retain_discovery(conn, moment, keep_days=1, enabled=True)
    prune_ping_samples(conn, cutoff_for(moment, 1))


def _exercise(conn: sqlite3.Connection, settings: Settings, index: int, cycles: int) -> int:
    repo = MonitoringRepository(conn)

    def cycle() -> int:
        nonlocal index
        moment = START + timedelta(minutes=index)
        refresh_selected(
            repo,
            settings,
            [1],
            enabled=True,
            reader=lambda _: [Neighbor(IP, MAC)],
            clock=lambda: moment,
        )
        saved = monitor_once(
            repo,
            settings,
            [1],
            enabled=True,
            probe=lambda _: PingResult(1, 1, 1.0),
            clock=lambda: moment,
        )
        if saved != 1:
            raise DatabaseError("synthetic monitoring did not save its expected sample")
        index += 1
        if index % 100 == 0:
            _prune(conn, moment)
        return saved

    result = run_periodic(cycle, cycles=cycles, interval_seconds=60, wait=lambda _: False)
    if result.interrupted:
        raise KeyboardInterrupt
    _prune(conn, START + timedelta(minutes=index - 1))
    return index


def _window(
    conn: sqlite3.Connection, settings: Settings, index: int, cycles: int, path: Path
) -> tuple[int, Window]:
    gc.collect()
    before = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    wall = perf_counter()
    cpu = process_time()
    index = _exercise(conn, settings, index, cycles)
    gc.collect()
    cpu_elapsed = process_time() - cpu
    wall_elapsed = perf_counter() - wall
    after, peak = tracemalloc.get_traced_memory()
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM sightings WHERE source='discovery'), "
        "(SELECT COUNT(*) FROM sightings WHERE source='ping'), (SELECT COUNT(*) FROM scans)"
    ).fetchone()
    wal = path.with_name(path.name + "-wal")
    return index, Window(
        cycles=cycles,
        wall_seconds=wall_elapsed,
        cpu_seconds=cpu_elapsed,
        python_before_bytes=before,
        python_after_bytes=after,
        python_delta_bytes=after - before,
        python_peak_bytes=peak,
        discovery_rows=int(row[0]),
        ping_rows=int(row[1]),
        scans=int(row[2]),
        database_bytes=path.stat().st_size,
        wal_bytes=wal.stat().st_size if wal.is_file() else 0,
    )


def profile_resources(*, cycles: int = 1000, warmup: int = 1500) -> Profile:
    """Measure two windows; no user configuration, targets or database paths accepted."""
    for value in (cycles, warmup):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5000:
            raise ConfigError("cycles and warmup must be integers between 1 and 5000")
    if tracemalloc.is_tracing():
        raise ConfigError("resource profiling refuses to replace an existing tracemalloc session")
    tracemalloc.start()
    try:
        with TemporaryDirectory(prefix="nettracker-profile-") as directory:
            path = Path(directory) / "synthetic.db"
            with closing(connect(path)) as conn:
                migrate(conn)
                repo = MonitoringRepository(conn)
                repo.upsert_device(MAC, seen_at=START)
                settings = Settings.model_validate(
                    {
                        "allowed_subnets": ["192.168.1.0/24"],
                        "database_path": str(path),
                        "monitor": {"enabled": True},
                    }
                )
                index = _exercise(conn, settings, 0, warmup)
                windows: list[Window] = []
                for _ in range(2):
                    index, window = _window(conn, settings, index, cycles, path)
                    windows.append(window)
                return Profile(warmup, cycles, sys.version.split()[0], sys.platform, tuple(windows))
    finally:
        tracemalloc.stop()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline synthetic monitoring resource profile")
    parser.add_argument(
        "--cycles",
        type=int,
        default=1000,
        help="cycles per measured window (1-5000)",
    )
    parser.add_argument("--warmup", type=int, default=1500, help="warmup cycles (1-5000)")
    args = parser.parse_args(argv)
    try:
        report = profile_resources(cycles=args.cycles, warmup=args.warmup)
    except KeyboardInterrupt:
        print("profile interrupted", file=sys.stderr)
        return 130
    except (NetTrackerError, OSError, sqlite3.Error) as exc:
        print(f"profile failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
