"""Allocation-summary privacy, deterministic bounds and signed accounting."""

import json
from dataclasses import asdict
from pathlib import Path

from nettracker.allocation_diagnostics import summarize_allocations


def test_project_labels_and_private_paths_are_redacted(tmp_path: Path) -> None:
    root = tmp_path / "package"
    project = str(root / "db" / "repository.py")
    private = str(tmp_path / "private-home" / "secret.py")
    summary = summarize_allocations(
        [(project, 12, 100, 2), (project, 12, -20, -1), (private, 3, 1000, 9)],
        package_root=root,
    )
    assert len(summary.entries) == 1
    change = summary.entries[0]
    assert (change.source, change.line, change.size_diff_bytes, change.count_diff) == (
        "nettracker/db/repository.py",
        12,
        80,
        1,
    )
    assert (summary.external_size_diff_bytes, summary.external_count_diff) == (1000, 9)
    encoded = json.dumps(asdict(summary))
    assert str(tmp_path) not in encoded
    assert "private-home" not in encoded
    assert "secret.py" not in encoded


def test_top_ten_preserves_omitted_totals(tmp_path: Path) -> None:
    source = str(tmp_path / "service.py")
    rows = [(source, number, number, 1) for number in range(1, 14)]
    summary = summarize_allocations(rows, package_root=tmp_path)
    assert len(summary.entries) == 10
    assert [entry.line for entry in summary.entries] == list(range(13, 3, -1))
    assert summary.other_project_size_diff_bytes == 6
    assert summary.other_project_count_diff == 3
    assert sum(entry.size_diff_bytes for entry in summary.entries) + 6 == 91


def test_negative_changes_and_ties_are_deterministic(tmp_path: Path) -> None:
    first = str(tmp_path / "a.py")
    second = str(tmp_path / "b.py")
    summary = summarize_allocations(
        [(second, 2, 10, 2), (first, 3, -16, -4), (first, 1, 10, 1)],
        package_root=tmp_path,
    )
    assert [entry.size_diff_bytes for entry in summary.entries] == [-16, 10, 10]
    assert [entry.source for entry in summary.entries] == [
        "nettracker/a.py",
        "nettracker/a.py",
        "nettracker/b.py",
    ]


def test_external_traversal_and_non_source_names_are_hidden(tmp_path: Path) -> None:
    root = tmp_path / "package"
    filenames = [
        str(root / ".." / "private.py"),
        str(root / "config.toml"),
        str(root / "private\nname.py"),
        r"C:\Users\PrivateUser\outside.py",
    ]
    summary = summarize_allocations(
        [(filename, 1, -10, -1) for filename in filenames], package_root=root
    )
    assert summary.entries == ()
    assert summary.external_size_diff_bytes == -40
    assert summary.external_count_diff == -4
    assert "PrivateUser" not in json.dumps(asdict(summary))


def test_empty_and_zero_changes_are_omitted(tmp_path: Path) -> None:
    summary = summarize_allocations([(str(tmp_path / "empty.py"), 1, 0, 0)], package_root=tmp_path)
    assert summary.entries == ()
    assert summary.other_project_size_diff_bytes == 0
    assert summary.external_size_diff_bytes == 0


def test_equivalent_paths_are_grouped(tmp_path: Path) -> None:
    summary = summarize_allocations(
        [(str(tmp_path / "db" / ".." / "a.py"), 5, 2, 1), (str(tmp_path / "a.py"), 5, 3, 2)],
        package_root=tmp_path,
    )
    assert len(summary.entries) == 1
    assert summary.entries[0].size_diff_bytes == 5
    assert summary.entries[0].count_diff == 3
