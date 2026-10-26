"""Read-only, fixed-size ICMP time buckets without inferring temporal uptime."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nettracker.errors import DatabaseError

BUCKET_COUNT = 96
WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
_SQL = (
    "SELECT CAST((CAST(strftime('%s', substr(seen_at, 1, 19)) AS INTEGER) - ?) / ? AS INTEGER), "
    "COUNT(*), SUM(CASE WHEN online = 1 THEN 1 ELSE 0 END), "
    "AVG(CASE WHEN online = 1 THEN latency_ms END), "
    "MAX(CASE WHEN online = 1 THEN latency_ms END) "
    "FROM sightings WHERE device_id = ? AND source = 'ping' "
    "AND seen_at >= ? AND seen_at < ? GROUP BY 1 ORDER BY 1"
)


@dataclass(frozen=True)
class Bucket:
    start: str
    end: str
    count: int
    replies: int
    mean_ms: float | None
    peak_ms: float | None

    @property
    def status(self) -> str:
        if not self.count:
            return "unknown"
        if not self.replies:
            return "no_reply"
        return "reply" if self.replies == self.count else "mixed"


@dataclass(frozen=True)
class TimeSeries:
    window: str
    start: str
    end: str
    minutes: int
    buckets: tuple[Bucket, ...]

    @property
    def count(self) -> int:
        return sum(bucket.count for bucket in self.buckets)

    @property
    def replies(self) -> int:
        return sum(bucket.replies for bucket in self.buckets)

    @property
    def ratio(self) -> float | None:
        return self.replies / self.count * 100 if self.count else None

    @property
    def scale_ms(self) -> float:
        return max(1.0, max((bucket.peak_ms or 0.0 for bucket in self.buckets), default=0.0))


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="microseconds")


def load_series(
    conn: sqlite3.Connection, device_id: int, now: datetime, window: str = "24h"
) -> TimeSeries:
    """Aggregate all pings in [start, end), returning exactly 96 chronological buckets."""
    if window not in WINDOWS:
        raise ValueError("window must be 24h or 7d")
    if isinstance(device_id, bool) or device_id <= 0:
        raise ValueError("device_id must be positive")
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    end = now.astimezone(UTC).replace(microsecond=0)
    start = end - WINDOWS[window]
    seconds = int(WINDOWS[window].total_seconds()) // BUCKET_COUNT
    try:
        rows = conn.execute(
            _SQL, (int(start.timestamp()), seconds, device_id, _stamp(start), _stamp(end))
        ).fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError("cannot read ICMP history") from exc
    populated: dict[int, Bucket] = {}
    for row in rows:
        if row[0] is None or not 0 <= int(row[0]) < BUCKET_COUNT:
            raise DatabaseError("invalid ICMP history timestamp")
        index = int(row[0])
        left = start + timedelta(seconds=index * seconds)
        populated[index] = Bucket(
            _stamp(left),
            _stamp(left + timedelta(seconds=seconds)),
            int(row[1]),
            int(row[2]),
            float(row[3]) if row[3] is not None else None,
            float(row[4]) if row[4] is not None else None,
        )
    buckets = tuple(
        populated.get(
            index,
            Bucket(
                _stamp(start + timedelta(seconds=index * seconds)),
                _stamp(start + timedelta(seconds=(index + 1) * seconds)),
                0,
                0,
                None,
                None,
            ),
        )
        for index in range(BUCKET_COUNT)
    )
    return TimeSeries(window, _stamp(start), _stamp(end), seconds // 60, buckets)
