"""Bounded, offline loading of an optional local IEEE MA-L registry."""

import csv
import logging
from io import StringIO
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_OUI_PATH = Path("data/oui/oui.csv")
MAX_REGISTRY_BYTES = 8 * 1024 * 1024


def parse_ma_l_csv(text: str) -> dict[str, str]:
    """Read IEEE's Registry,Assignment,Organization Name CSV fields."""
    reader = csv.DictReader(StringIO(text))
    required = {"Registry", "Assignment", "Organization Name"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("invalid IEEE MA-L CSV header")
    vendors: dict[str, str] = {}
    for row in reader:
        if row["Registry"] != "MA-L":
            continue
        prefix = (row["Assignment"] or "").upper()
        name = (row["Organization Name"] or "").strip()
        if len(prefix) != 6 or any(char not in "0123456789ABCDEF" for char in prefix):
            continue
        if name and name.casefold() != "private":
            vendors[prefix] = name
    return vendors


def load_local_registry(path: Path | None = None) -> dict[str, str] | None:
    """Read the conventional file once; an unavailable registry never triggers a download."""
    selected = DEFAULT_OUI_PATH if path is None else path
    try:
        with selected.open("rb") as stream:
            data = stream.read(MAX_REGISTRY_BYTES + 1)
        if len(data) > MAX_REGISTRY_BYTES:
            raise ValueError("IEEE registry exceeds size limit")
        vendors = parse_ma_l_csv(data.decode("utf-8-sig"))
        if not vendors:
            raise ValueError("IEEE registry has no public MA-L entries")
    except FileNotFoundError:
        logger.debug("local IEEE registry absent; vendor enrichment unavailable")
        return None
    except (OSError, UnicodeDecodeError, ValueError, csv.Error) as exc:
        logger.warning(
            "local IEEE registry ignored (%s); discovery remains available", type(exc).__name__
        )
        return None
    logger.info("loaded local IEEE registry: %d public MA-L entries", len(vendors))
    return vendors
