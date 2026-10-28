"""Explicit, bounded IEEE registry download and atomic local installation."""

import argparse
import csv
import logging
import os
import sys
from collections.abc import Callable, Sequence
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

import httpx

from nettracker.discovery.oui_registry import (
    DEFAULT_OUI_PATH,
    MAX_REGISTRY_BYTES,
    parse_ma_l_csv,
)
from nettracker.errors import NetTrackerError

SOURCE_URL = "https://standards-oui.ieee.org/oui/oui.csv"
TRANSFER_BUDGET_SECONDS = 30.0
NETWORK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
logger = logging.getLogger(__name__)


class RegistryUpdateError(NetTrackerError):
    """The registry could not be downloaded, validated or installed safely."""


def download_registry(
    *,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = monotonic,
) -> bytes:
    """Fetch only the fixed source; tests inject a transport instead of opening sockets."""
    deadline = clock() + TRANSFER_BUDGET_SECONDS
    try:
        with (
            httpx.Client(
                transport=transport,
                timeout=NETWORK_TIMEOUT,
                follow_redirects=False,
                trust_env=False,
                verify=True,
                headers={"Accept": "text/csv", "Accept-Encoding": "identity"},
            ) as client,
            client.stream("GET", SOURCE_URL, timeout=NETWORK_TIMEOUT) as response,
        ):
            if clock() > deadline:
                raise RegistryUpdateError("IEEE transfer time budget exceeded")
            if response.status_code != 200:
                raise RegistryUpdateError(f"IEEE server returned HTTP {response.status_code}")
            encoding = response.headers.get("content-encoding", "").strip().lower()
            if encoding not in ("", "identity"):
                raise RegistryUpdateError("compressed IEEE responses are refused")
            declared: int | None = None
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    declared = int(length)
                except ValueError as exc:
                    raise RegistryUpdateError("invalid IEEE content length") from exc
                if not 0 <= declared <= MAX_REGISTRY_BYTES:
                    raise RegistryUpdateError("IEEE registry exceeds size limit")
            data = bytearray()
            for chunk in response.iter_bytes():
                if clock() > deadline:
                    raise RegistryUpdateError("IEEE transfer time budget exceeded")
                if len(data) + len(chunk) > MAX_REGISTRY_BYTES:
                    raise RegistryUpdateError("IEEE registry exceeds size limit")
                data.extend(chunk)
            if clock() > deadline:
                raise RegistryUpdateError("IEEE transfer time budget exceeded")
            if declared is not None and len(data) != declared:
                raise RegistryUpdateError("incomplete IEEE response")
            return bytes(data)
    except httpx.HTTPError as exc:
        raise RegistryUpdateError("IEEE HTTPS request failed") from exc


def _validate_registry(data: bytes) -> int:
    if len(data) > MAX_REGISTRY_BYTES:
        raise RegistryUpdateError("IEEE registry exceeds size limit")
    try:
        text = data.decode("utf-8-sig")
        reader = csv.reader(StringIO(text), strict=True)
        header = next(reader, None)
        required = {"Registry", "Assignment", "Organization Name"}
        if header is None or not required.issubset(header):
            raise RegistryUpdateError("invalid IEEE CSV header")
        for row in reader:
            if row and len(row) != len(header):
                raise RegistryUpdateError("inconsistent IEEE CSV row")
        vendors = parse_ma_l_csv(text)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise RegistryUpdateError("invalid IEEE CSV content") from exc
    if not vendors:
        raise RegistryUpdateError("IEEE registry has no public MA-L entries")
    return len(vendors)


def _check_destination(destination: Path) -> None:
    if destination.suffix.lower() != ".csv":
        raise RegistryUpdateError("registry destination must end in .csv")
    if destination.is_symlink() or destination.is_dir():
        raise RegistryUpdateError("registry destination must not be a symlink or directory")


def install_registry(data: bytes, destination: Path = DEFAULT_OUI_PATH) -> int:
    """Validate before writing; replace only after the sibling temporary file is closed."""
    _check_destination(destination)
    entries = _validate_registry(data)
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".oui-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _check_destination(destination)
        temporary.replace(destination)
        temporary = None
    except OSError as exc:
        raise RegistryUpdateError("cannot install IEEE registry; previous file preserved") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("cannot remove IEEE registry temporary file")
    return entries


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly install the public IEEE MA-L CSV.")
    parser.add_argument("--apply", action="store_true", help="authorize download and installation")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUI_PATH)
    args = parser.parse_args(argv)
    if not args.apply:
        print(f"Preview only: would download {SOURCE_URL} and install {args.output}")
        print("Nothing downloaded or written. Pass --apply to proceed.")
        return 0
    try:
        _check_destination(args.output)
        data = download_registry()
        entries = install_registry(data, args.output)
    except (RegistryUpdateError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted; installation was not confirmed", file=sys.stderr)
        return 130
    print(f"IEEE registry installed: {entries} MA-L entries at {args.output}")
    print("No device data was sent. Run a discovery cycle to enrich observed devices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
