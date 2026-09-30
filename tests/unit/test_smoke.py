"""Smoke test: the package imports and exposes a version."""

from nettracker import __version__


def test_version_is_defined() -> None:
    assert __version__
    assert __version__.count(".") >= 2
