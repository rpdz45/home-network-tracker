"""Explicit per-device router DNS command; no implicit migration or discovery."""

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from nettracker.config import load_settings
from nettracker.db import LATEST_VERSION
from nettracker.discovery.identity_service import enrich_router_dns
from nettracker.errors import ConfigError, DatabaseError, NetTrackerError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nettracker identify-dns",
        description="Collect DNS names for one discovered device using an explicit local server.",
    )
    parser.add_argument("-c", "--config", type=Path)
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--dns-server", required=True, help="authorized private IPv4 DNS server")
    parser.add_argument("--enable-dns", action="store_true", help="authorize DNS and local storage")
    parser.add_argument("--timeout", type=float, default=1.5, help="DNS timeout in seconds (0.2-5)")
    args = parser.parse_args(argv)
    try:
        if not args.enable_dns:
            raise ConfigError("identify-dns requires --enable-dns")
        if args.device_id <= 0:
            raise ConfigError("device ID must be positive")
        settings = load_settings(args.config, dotenv_path=Path(".env"))
        path = settings.database_path.resolve()
        if not path.is_file():
            raise ConfigError("database missing; run nettracker init-db first")
        with closing(
            sqlite3.connect(
                path.as_uri() + "?mode=rw", uri=True, timeout=5.0, isolation_level=None
            )
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row is None or row[0] != LATEST_VERSION:
                raise ConfigError("database schema is not current; run nettracker init-db")
            count = enrich_router_dns(
                conn,
                device_id=args.device_id,
                server=args.dns_server,
                allowed_subnets=tuple(settings.allowed_subnets),
                enabled=True,
                timeout=args.timeout,
            )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except NetTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError:
        print("error: invalid DNS request or device binding; nothing inferred", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError):
        error = DatabaseError("cannot open or use DNS identity database")
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"DNS identification complete: {count} observation(s) stored (including lookup failures)")
    return 0
