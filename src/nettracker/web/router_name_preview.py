"""Best-effort read-only matching of an already authorized router snapshot."""

import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from nettracker.routers.bbox_session import BboxSnapshot
from nettracker.routers.device_names import NameCandidate, RouterNameSource, preview_names
from nettracker.routers.livebox5 import LiveboxSnapshot
from nettracker.routers.name_reports import bbox_names, livebox_names


def preview_snapshot(
    path: Path,
    snapshot: LiveboxSnapshot | BboxSnapshot,
    address: str,
    secret: str,
    retrieved_at: datetime,
) -> tuple[tuple[NameCandidate, ...], bool]:
    """Return proposals and an unavailable flag, never creating or migrating a DB.

    No refresh is performed. Binding matches are proposals, not physical identity
    verification or authorization for a later write. No raw database error is shown.
    """
    try:
        source: RouterNameSource
        if isinstance(snapshot, LiveboxSnapshot):
            reports = livebox_names(snapshot)
            source = "livebox5"
        else:
            reports = bbox_names(snapshot)
            source = "bbox"
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            candidates = preview_names(
                conn,
                reports,
                source=source,
                endpoint=urlsplit(address).hostname or "",
                retrieved_at=retrieved_at,
                secret=secret,
            )
        finally:
            conn.close()
    except (sqlite3.Error, ValueError, OSError):
        return (), True
    return candidates, False
