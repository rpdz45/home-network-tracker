"""Explicit periodic ICMP monitoring; sequential cycles and interruptible fixed delays."""

import argparse
import signal
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
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
    parser.add_argument(
        "--prune-ping",
        action="store_true",
        help="delete expired ping samples database-wide in bounded single batches",
    )
    parser.add_argument(
        "--prune-every-cycles", type=int, help="purge cadence (1-1000000; default 100)"
    )
    parser.add_argument(
        "--prune-discovery",
        action="store_true",
        help="delete superseded discoveries and unused old scans database-wide",
    )
    parser.add_argument(
        "--discovery-prune-every-cycles", type=int, help="discovery purge cadence (default 100)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cycles", type=int)
    mode.add_argument("--continuous", action="store_true")
    args = parser.parse_args(argv)
    if not args.enable_monitoring:
        parser.error("--enable-monitoring is required")
    if args.prune_every_cycles is not None:
        if not args.prune_ping:
            parser.error("--prune-every-cycles requires --prune-ping")
        if not 1 <= args.prune_every_cycles <= 1_000_000:
            parser.error("prune cadence must be between 1 and 1000000 cycles")
    prune_every = 100 if args.prune_every_cycles is None else args.prune_every_cycles
    discovery_every = args.discovery_prune_every_cycles
    if discovery_every is not None:
        if not args.prune_discovery:
            parser.error("--discovery-prune-every-cycles requires --prune-discovery")
        if not 1 <= discovery_every <= 1_000_000:
            parser.error("discovery prune cadence must be between 1 and 1000000 cycles")
    else:
        discovery_every = 100
    count = None if args.continuous else (args.cycles if args.cycles is not None else 1)
    try:
        _limits(args.interval_seconds, count)
    except ValueError as exc:
        parser.error(str(exc))

    from nettracker.config import load_settings
    from nettracker.db import LATEST_VERSION, connect
    from nettracker.db.discovery_retention import retain_discovery
    from nettracker.db.monitoring import MonitoringRepository
    from nettracker.db.retention import cutoff_for, prune_ping_samples
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
        if args.prune_ping and not settings.retention.enabled:
            raise ConfigError("--prune-ping requires retention.enabled=true")
        if args.prune_discovery and not settings.discovery_retention.enabled:
            raise ConfigError("--prune-discovery requires discovery_retention.enabled=true")
        if not settings.database_path.is_file():
            raise ConfigError("database missing; run nettracker init-db first")
        with closing(connect(settings.database_path)) as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row is None or row[0] != LATEST_VERSION:
                raise ConfigError("database schema is not current; run nettracker init-db")
            repo = MonitoringRepository(conn)

            completed = 0
            pruned = 0
            pruned_observations = 0
            pruned_scans = 0

            def cycle() -> int:
                nonlocal completed, pruned, pruned_observations, pruned_scans
                if args.refresh_passive:
                    refresh_selected(repo, settings, args.device_id, enabled=True)
                if stopped.is_set():
                    return 0
                saved = monitor_once(repo, settings, args.device_id, enabled=True)
                completed += 1
                if args.prune_ping and completed % prune_every == 0 and not stopped.is_set():
                    if conn.in_transaction:
                        raise ConfigError("ping retention cannot run inside an open transaction")
                    pruned += prune_ping_samples(
                        conn,
                        cutoff_for(datetime.now(UTC), settings.retention.keep_days),
                        batch_size=settings.retention.batch_size,
                        max_batches=1,
                    )
                if (
                    args.prune_discovery
                    and completed % discovery_every == 0
                    and not stopped.is_set()
                ):
                    discovery = retain_discovery(
                        conn,
                        datetime.now(UTC),
                        keep_days=settings.discovery_retention.keep_days,
                        batch_size=settings.discovery_retention.batch_size,
                        max_batches=1,
                        enabled=True,
                    )
                    pruned_observations += discovery.observations
                    pruned_scans += discovery.scans
                return saved

            result = run_periodic(
                cycle,
                interval_seconds=args.interval_seconds,
                cycles=count,
                stop=stopped,
            )
        print(f"cycles={result.cycles} measurements={result.measurements}")
        if args.prune_ping:
            print(f"pruned_ping_samples={pruned}")
        if args.prune_discovery:
            print(
                f"pruned_discovery_observations={pruned_observations} pruned_scans={pruned_scans}"
            )
        return 130 if result.interrupted else 0
    except (NetTrackerError, sqlite3.Error) as exc:
        print(f"monitoring stopped: {type(exc).__name__}")
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
