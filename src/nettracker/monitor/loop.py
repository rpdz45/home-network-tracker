"""Explicit periodic ICMP monitoring; sequential cycles and interruptible fixed delays."""

import argparse
import signal
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import FrameType


@dataclass(frozen=True)
class LoopResult:
    cycles: int
    measurements: int
    interrupted: bool = False


def _limits(interval_seconds: int, cycles: int | None) -> None:
    if isinstance(interval_seconds, bool) or not 10 <= interval_seconds <= 86_400:
        raise ValueError("interval must be between 10 and 86400 seconds")
    if cycles is not None and (isinstance(cycles, bool) or not 1 <= cycles <= 1_000_000):
        raise ValueError("cycles must be between 1 and 1000000, or None for continuous mode")


def run_periodic(
    cycle: Callable[[], int],
    *,
    interval_seconds: int = 60,
    cycles: int | None = 1,
    stop: Event | None = None,
    wait: Callable[[float], bool] | None = None,
) -> LoopResult:
    """Wait after each completed cycle; errors propagate and no cycle overlaps another."""
    _limits(interval_seconds, cycles)
    stopped = Event() if stop is None else stop
    pause = stopped.wait if wait is None else wait
    completed = 0
    measurements = 0
    try:
        while not stopped.is_set():
            measurements += cycle()
            completed += 1
            if cycles is not None and completed >= cycles:
                break
            if pause(interval_seconds):
                break
    except KeyboardInterrupt:
        return LoopResult(completed, measurements, interrupted=True)
    return LoopResult(completed, measurements)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit periodic ICMP monitoring")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--device-id", type=int, action="append", required=True)
    parser.add_argument("--enable-monitoring", action="store_true")
    parser.add_argument("--refresh-passive", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cycles", type=int)
    mode.add_argument("--continuous", action="store_true")
    args = parser.parse_args(argv)
    if not args.enable_monitoring:
        parser.error("--enable-monitoring is required")
    count = None if args.continuous else (args.cycles if args.cycles is not None else 1)
    try:
        _limits(args.interval_seconds, count)
    except ValueError as exc:
        parser.error(str(exc))

    from nettracker.config import load_settings
    from nettracker.db import LATEST_VERSION, connect
    from nettracker.db.monitoring import MonitoringRepository
    from nettracker.errors import ConfigError, NetTrackerError
    from nettracker.monitor.refresh import refresh_selected
    from nettracker.monitor.service import monitor_once

    stopped = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stopped.set()

    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        settings = load_settings(args.config, dotenv_path=Path(".env"))
        if not settings.monitor.enabled:
            raise ConfigError("monitor.enabled=true is required")
        if not settings.database_path.is_file():
            raise ConfigError("database missing; run nettracker init-db first")
        with closing(connect(settings.database_path)) as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row is None or row[0] != LATEST_VERSION:
                raise ConfigError("database schema is not current; run nettracker init-db")
            repo = MonitoringRepository(conn)

            def cycle() -> int:
                if args.refresh_passive:
                    refresh_selected(repo, settings, args.device_id, enabled=True)
                if stopped.is_set():
                    return 0
                return monitor_once(repo, settings, args.device_id, enabled=True)

            result = run_periodic(
                cycle,
                interval_seconds=args.interval_seconds,
                cycles=count,
                stop=stopped,
            )
        print(f"cycles={result.cycles} measurements={result.measurements}")
        return 130 if result.interrupted else 0
    except (NetTrackerError, sqlite3.Error) as exc:
        print(f"monitoring stopped: {type(exc).__name__}")
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
