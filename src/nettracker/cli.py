"""Command-line interface."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from nettracker import __version__
from nettracker.config import Settings, load_settings
from nettracker.db import Repository, connect, migrate
from nettracker.discovery.collector import collect_passive
from nettracker.discovery.vendor import parse_ma_l_csv
from nettracker.errors import ConfigError, NetTrackerError

logger = logging.getLogger("nettracker")

COMMANDS = {
    "check-config": "Validate the configuration and print a summary (secrets are never shown).",
    "init-db": "Create or upgrade the SQLite database schema.",
    "scan-once": "Read the local neighbor cache once and save in-scope observations.",
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
        if name == "scan-once":
            sub.add_argument(
                "--oui-file",
                type=Path,
                default=None,
                help="optional local IEEE MA-L CSV file (no automatic download)",
            )
    return parser


def _check_config(settings: Settings) -> int:
    token_state = "set" if settings.api.token is not None else "not set"
    subnets = ", ".join(str(network) for network in settings.allowed_subnets)
    print("Configuration OK")
    print(f"allowed_subnets: {subnets}")
    print(f"database_path: {settings.database_path}")
    print(f"scan: mode={settings.scan.mode} interval={settings.scan.interval_seconds}s")
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


def _scan_once(settings: Settings, oui_file: Path | None = None) -> int:
    if settings.scan.mode != "passive":
        raise ConfigError(
            "scan-once supports passive mode only; active discovery is not implemented"
        )
    vendors: dict[str, str] | None = None
    if oui_file is not None:
        try:
            vendors = parse_ma_l_csv(oui_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ConfigError(f"cannot load IEEE vendor file {oui_file}: {exc}") from exc
    logger.warning("passive mode: system neighbor cache only; no network probes")
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        repo = Repository(conn)
        if vendors is None:
            count = collect_passive(repo, settings.allowed_subnets)
        else:
            count = collect_passive(repo, settings.allowed_subnets, vendors=vendors)
    finally:
        conn.close()
    print(f"Passive discovery complete: {count} observation(s) from the system neighbor cache")
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
        return _scan_once(settings, args.oui_file)
    except NetTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
