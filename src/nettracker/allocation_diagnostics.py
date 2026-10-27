"""Bounded allocation summaries without absolute paths, source text or object contents."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MAX_ENTRIES = 10


@dataclass(frozen=True)
class AllocationChange:
    source: str
    line: int
    size_diff_bytes: int
    count_diff: int


@dataclass(frozen=True)
class AllocationSummary:
    entries: tuple[AllocationChange, ...]
    other_project_size_diff_bytes: int
    other_project_count_diff: int
    external_size_diff_bytes: int
    external_count_diff: int


def summarize_allocations(
    changes: Iterable[tuple[str, int, int, int]], *, package_root: Path | None = None
) -> AllocationSummary:
    """Group signed differences; show at most ten safe package-relative source labels."""
    root = (Path(__file__).parent if package_root is None else package_root).resolve()
    grouped: dict[tuple[str, int], tuple[int, int]] = {}
    external_size = 0
    external_count = 0
    relative: Path | None = None
    for filename, line, size, count in changes:
        try:
            relative = Path(filename).resolve().relative_to(root)
        except (OSError, ValueError):
            relative = None
        label = relative.as_posix() if relative is not None else ""
        safe = (
            relative is not None
            and relative.suffix == ".py"
            and line > 0
            and all(char.isascii() and (char.isalnum() or char in "/_.-") for char in label)
        )
        if not safe:
            external_size += size
            external_count += count
            continue
        key = ("nettracker/" + label, line)
        old_size, old_count = grouped.get(key, (0, 0))
        grouped[key] = (old_size + size, old_count + count)
    entries = [
        AllocationChange(source, line, size, count)
        for (source, line), (size, count) in grouped.items()
        if size != 0 or count != 0
    ]
    entries.sort(key=lambda entry: (-abs(entry.size_diff_bytes), entry.source, entry.line))
    return AllocationSummary(
        entries=tuple(entries[:MAX_ENTRIES]),
        other_project_size_diff_bytes=sum(entry.size_diff_bytes for entry in entries[MAX_ENTRIES:]),
        other_project_count_diff=sum(entry.count_diff for entry in entries[MAX_ENTRIES:]),
        external_size_diff_bytes=external_size,
        external_count_diff=external_count,
    )
