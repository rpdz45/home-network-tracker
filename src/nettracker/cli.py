"""Command-line interface."""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from nettracker import __version__
from nettracker.config import Settings, load_settings
from nettracker.db import Repository, connect, migrate
from nettracker.db.health import collector_health, record_stale_event
from nettracker.db.monitoring import MonitoringRepository
from nettracker.db.retention import count_prunable, cutoff_for, prune_ping_samples
from nettracker.discovery.collector import ScanMode, collect_observations, collect_passive
from nettracker.discovery.mdns import mdns_hostname
from nettracker.discovery.names import reverse_hostname
from nettracker.discovery.passive import read_neighbors
from nettracker.discovery.strategy import discover_with_fallback
from nettracker.discovery.vendor import parse_ma_l_csv
from nettracker.errors import ConfigError, NetTrackerError
from nettracker.monitor.service import monitor_once

logger = logging.getLogger("nettracker")

STALE_EXIT_CODE = 3

COMMANDS = {
    "check-config": "Validate the configuration and print a summary (secrets are never shown).",
    "health-check": "Report collector health; record a collector_stale event once per outage.",
    "init-db": "Create or upgrade the SQLite database schema.",
    "monitor-once": "Measure ICMP reachability for explicitly selected discovered devices.",
    "prune-history": "Preview or delete old ping samples (preview only unless authorized).",
    "scan-once": "Discover scoped neighbors once and save observations.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nettracker",
        description="Home network tracker: device discovery, monitoring and alerts.",
    )
    parser.add_argument("--version", action="version", version=f"nettracker {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in COMMANDS.items():
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        sub.add_argument(
            "-c",
            "--config",
            type=Path,
            default=None,
            help="path to the TOML config (default: $NETTRACKER_CONFIG or ./config.toml)",
        )
        if name == "monitor-once":
            sub.add_argument(
                "--device-id",
                action="append",
                type=int,
                required=True,
                help="explicit discovered device ID (repeatable, max 64)",
            )
            sub.add_argument(
                "--enable-monitoring",
                action="store_true",
                help="authorize ICMP packets; requires monitor.enabled=true",
            )
        if name == "prune-history":
            sub.add_argument(
                "--apply",
                action="store_true",
                help="actually delete old ping samples; requires retention.enabled=true",
            )
        if name == "scan-once":
            sub.add_argument(
                "--resolve-names",
                action="store_true",
                help="opt in to reverse DNS via the system resolver (may send DNS queries)",
            )
            sub.add_argument(
                "--resolve-mdns",
                action="store_true",
                help="opt in to targeted mDNS PTR queries on UDP 5353 (sends packets)",
            )
            sub.add_argument(
                "--oui-file",
                type=Path,
                default=None,
                help="optional local IEEE MA-L CSV file (no automatic download)",
            )
            sub.add_argument("--target", help="explicit RFC1918 IPv4 host or CIDR for active ARP")
            sub.add_argument(
                "--enable-active",
                action="store_true",
                help="explicitly authorize active ARP (requires scan.mode=active and --target)",
            )
    return parser


def _check_config(settings: Settings) -> int:
    token_state = "set" if settings.api.token is not None else "not set"
    subnets = ", ".join(str(network) for network in settings.allowed_subnets)
    print("Configuration OK")
    print(f"allowed_subnets: {subnets}")
    print(f"known_devices: {len(settings.known_devices)} configured MAC address(es)")
    print(f"database_path: {settings.database_path}")
    print(f"scan: mode={settings.scan.mode} interval={settings.scan.interval_seconds}s")
    print(
        f"retention: enabled={str(settings.retention.enabled).lower()} "
        f"keep_days={settings.retention.keep_days}"
    )
    print(f"health: stale_after_minutes={settings.health.stale_after_minutes}")
    print(f"alerts: dry_run={str(settings.alerts.dry_run).lower()}")
    print(f"api: {settings.api.host}:{settings.api.port} (token: {token_state})")
    return 0


def _init_db(settings: Settings) -> int:
    conn = connect(settings.database_path)
    try:
        version = migrate(conn)
    finally:
        conn.close()
    logger.info("database ready at %s", settings.database_path)
    print(f"Database ready: {settings.database_path} (schema version {version})")
    return 0


def _health_check(settings: Settings) -> int:
    now = datetime.now(UTC)
    minutes = settings.health.stale_after_minutes
    threshold = minutes * 60
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        health = collector_health(conn, now, threshold)
        created = record_stale_event(conn, now, threshold) if health.stale else False
    finally:
        conn.close()
    if health.last_success_at is None:
        print("Collector: no successful scan recorded yet")
    else:
        state = "STALE" if health.stale else "OK"
        age = int(health.age_seconds or 0)
        print(
            f"Collector: {state} (last successful scan {health.last_success_at}, "
            f"{age}s ago, threshold {minutes} min)"
        )
    for problem in health.recent_problems:
        detail = problem.error or "unfinished"
        print(f"Recent problem: scan started {problem.started_at} status={problem.status} {detail}")
    if created:
        print("Event collector_stale recorded; no notification is sent by this command")
    return STALE_EXIT_CODE if health.stale else 0


def _prune_history(settings: Settings, apply: bool) -> int:
    if apply and not settings.retention.enabled:
        raise ConfigError("pruning requires retention.enabled=true and --apply")
    cutoff = cutoff_for(datetime.now(UTC), settings.retention.keep_days)
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        prunable = count_prunable(conn, cutoff)
        if not apply:
            print(
                f"Preview only: {prunable} ping sample(s) older than "
                f"{settings.retention.keep_days} day(s) would be deleted; nothing was changed"
            )
            return 0
        deleted = prune_ping_samples(
            conn,
            cutoff,
            batch_size=settings.retention.batch_size,
            max_batches=settings.retention.max_batches,
        )
    finally:
        conn.close()
    print(f"Pruning complete: {deleted} ping sample(s) deleted; other data untouched")
    return 0


def _scan_once(
    settings: Settings,
    oui_file: Path | None = None,
    target: str | None = None,
    enable_active: bool = False,
    resolve_names: bool = False,
    resolve_mdns: bool = False,
) -> int:
    if resolve_mdns and not settings.scan.mdns_enabled:
        raise ConfigError("mDNS requires scan.mdns_enabled=true and --resolve-mdns")
    active = settings.scan.mode == "active"
    if active and (not enable_active or target is None):
        raise ConfigError("passive mode only; active requires --enable-active and --target")
    if not active and (enable_active or target is not None):
        raise ConfigError("active ARP requires scan.mode=active, --enable-active and --target")
    vendors: dict[str, str] | None = None
    if oui_file is not None:
        try:
            vendors = parse_ma_l_csv(oui_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ConfigError(f"cannot load IEEE vendor file {oui_file}: {exc}") from exc

    resolved: dict[str, str | None] = {}

    def lookup(ip: str) -> str | None:
        if ip in resolved:
            return resolved[ip]
        if resolve_mdns:
            name = mdns_hostname(
                ip,
                settings.allowed_subnets,
                enabled=True,
                timeout=settings.scan.mdns_timeout_seconds,
            )
            if name is not None:
                resolved[ip] = name
                return name
        name = (
            reverse_hostname(ip, settings.allowed_subnets, enabled=True) if resolve_names else None
        )
        resolved[ip] = name
        return name

    if resolve_mdns:
        logger.warning("mDNS enabled: targeted active UDP 5353 queries; no multicast browsing")
    if resolve_names:
        logger.warning("reverse DNS enabled: system resolver may send queries outside the LAN")
    if active:
        result = discover_with_fallback(
            settings.allowed_subnets,
            target=target,
            active_enabled=True,
            nmap_enabled=settings.scan.nmap_fallback,
            nmap_timeout=settings.scan.nmap_timeout_seconds,
        )
        mode: ScanMode = (
            "passive" if result.source == "system_neighbor_cache" and not resolve_mdns else "active"
        )
        if result.degraded:
            if result.source == "active_nmap":
                print("Degraded mode: nmap host discovery fallback (active)")
            else:
                print("Degraded mode: system neighbor cache only")
        conn = connect(settings.database_path)
        try:
            migrate(conn)
            count = collect_observations(
                Repository(conn),
                settings.allowed_subnets,
                mode=mode,
                reader=lambda _: result.neighbors,
                vendors=vendors,
                hostname_lookup=lookup if resolve_names or resolve_mdns else None,
                known_devices=settings.known_devices,
            )
        finally:
            conn.close()
        print(f"Discovery complete: {count} observation(s) from {result.source}")
        return 0
    logger.warning("discovery from system neighbor cache; no ARP probes")
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        repo = Repository(conn)
        if resolve_mdns:
            count = collect_observations(
                repo,
                settings.allowed_subnets,
                mode="active",
                reader=read_neighbors,
                vendors=vendors,
                hostname_lookup=lookup,
                known_devices=settings.known_devices,
            )
        elif settings.known_devices:
            count = collect_passive(
                repo,
                settings.allowed_subnets,
                vendors=vendors,
                hostname_lookup=lookup if resolve_names or resolve_mdns else None,
                known_devices=settings.known_devices,
            )
        elif resolve_names:
            count = collect_passive(
                repo, settings.allowed_subnets, vendors=vendors, hostname_lookup=lookup
            )
        elif vendors is None:
            count = collect_passive(repo, settings.allowed_subnets)
        else:
            count = collect_passive(repo, settings.allowed_subnets, vendors=vendors)
    finally:
        conn.close()
    label = "Discovery with active mDNS" if resolve_mdns else "Passive discovery"
    print(f"{label} complete: {count} observation(s) from the system neighbor cache")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        settings = load_settings(args.config, dotenv_path=Path(".env"))
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        if args.command == "check-config":
            return _check_config(settings)
        if args.command == "init-db":
            return _init_db(settings)
        if args.command == "health-check":
            return _health_check(settings)
        if args.command == "prune-history":
            return _prune_history(settings, args.apply)
        if args.command == "monitor-once":
            if not args.enable_monitoring or not settings.monitor.enabled:
                raise ConfigError(
                    "monitoring requires monitor.enabled=true and --enable-monitoring"
                )
            conn = connect(settings.database_path)
            try:
                migrate(conn)
                count = monitor_once(
                    MonitoringRepository(conn), settings, args.device_id, enabled=True
                )
            finally:
                conn.close()
            print(f"Monitoring complete: {count} measurement(s); ICMP reachability is not identity")
            return 0
        return _scan_once(
            settings,
            args.oui_file,
            args.target,
            args.enable_active,
            args.resolve_names,
            args.resolve_mdns,
        )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except NetTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
