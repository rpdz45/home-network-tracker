"""Command-line interface."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from nettracker import __version__
from nettracker.config import Settings, load_settings
from nettracker.db import connect, migrate
from nettracker.errors import NetTrackerError

logger = logging.getLogger("nettracker")

COMMANDS = {
    "check-config": "Validate the configuration and print a summary (secrets are never shown).",
    "init-db": "Create or upgrade the SQLite database schema.",
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
        return _init_db(settings)
    except NetTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
