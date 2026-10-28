"""Offline tests for French display dates and daylight-saving transitions."""

from datetime import UTC, datetime

import pytest

from nettracker.web.formatting import paris_datetime


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "Non renseigné"),
        ("", "Non renseigné"),
        ("not-a-date", "Date invalide"),
        ("2026-10-28T14:07:14", "Fuseau non renseigné"),
        (datetime(2026, 10, 28, 14, 7), "Fuseau non renseigné"),
        ("2026-10-28T14:07:14.451290+00:00", "15:07 · 28/10/2026"),
        ("2026-07-15T14:07:00Z", "16:07 · 15/07/2026"),
        ("2026-01-15T14:07:00Z", "15:07 · 15/01/2026"),
        ("2026-03-29T00:30:00Z", "01:30 · 29/03/2026"),
        ("2026-03-29T01:30:00Z", "03:30 · 29/03/2026"),
        ("2026-10-25T00:30:00Z", "02:30 · 25/10/2026"),
        ("2026-10-25T01:30:00Z", "02:30 · 25/10/2026"),
        ("2026-10-28T14:07:00+02:00", "13:07 · 28/10/2026"),
        ("2026-10-28T23:30:00Z", "00:30 · 29/10/2026"),
        (datetime(2026, 10, 28, 14, 7, tzinfo=UTC), "15:07 · 28/10/2026"),
    ],
)
def test_paris_datetime(value: str | datetime | None, expected: str) -> None:
    assert paris_datetime(value) == expected


def test_paris_datetime_preserves_input() -> None:
    timestamp = datetime(2026, 10, 28, 14, 7, tzinfo=UTC)
    paris_datetime(timestamp)
    assert timestamp.isoformat() == "2026-10-28T14:07:00+00:00"
