"""CLI entrypoint; isolate discovery pruning while delegating existing commands."""

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from nettracker.config import Settings, load_settings
from nettracker.db import LATEST_VERSION
from nettracker.db.discovery_retention import DiscoveryRetentionResult, retain_discovery
from nettracker.errors import ConfigError, DatabaseError, NetTrackerError


def prune_discovery(settings: Settings, *, apply: bool = False) -> DiscoveryRetentionResult:
    """Open only an existing database; preview uses SQLite read-only mode, without migration."""
    policy = settings.discovery_retention
    if apply and not policy.enabled:
        raise ConfigError("pruning requires discovery_retention.enabled=true and --apply")
    try:
        path = settings.database_path.resolve()
        if not path.is_file():
            raise ConfigError("database missing; run nettracker init-db first")
    except OSError as exc:
        raise DatabaseError("cannot access discovery pruning database") from exc
    mode = "rw" if apply else "ro"
    uri = path.as_uri() + "?mode=" + mode
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row is None or row[0] != LATEST_VERSION:
                raise ConfigError("database schema is not current; run nettracker init-db")
            return retain_discovery(
                conn,
                datetime.now(UTC),
                keep_days=policy.keep_days,
                batch_size=policy.batch_size,
                max_batches=policy.max_batches,
                enabled=apply,
            )
    except sqlite3.Error as exc:
        raise DatabaseError("cannot open or use discovery pruning database") from exc


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        from nettracker.cli import build_parser

        parser = build_parser()
        parser.epilog = "Additional command: prune-discovery (use prune-discovery --help)."
        parser.print_help()
        return 0 if arguments else 2
    if arguments[0] != "prune-discovery":
        from nettracker.cli import main as existing_main

        return existing_main(arguments)
    parser = argparse.ArgumentParser(
        prog="nettracker prune-discovery",
        description="Preview discovery retention; deletion requires config activation and --apply.",
    )
    parser.add_argument("-c", "--config", type=Path)
    parser.add_argument("--apply", action="store_true", help="explicitly authorize deletion")
    args = parser.parse_args(arguments[1:])
    try:
        settings = load_settings(args.config, dotenv_path=Path(".env"))
        result = prune_discovery(settings, apply=args.apply)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except NetTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    label = "Deleted" if result.applied else "Preview only (before observation removal)"
    print(f"{label}: observations={result.observations} scans={result.scans}")
    if not result.applied:
        print("No data deleted; apply may release additional scans after observation removal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
