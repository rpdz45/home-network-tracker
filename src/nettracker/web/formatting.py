"""French display dates without modifying stored UTC timestamps."""

from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def paris_datetime(value: str | datetime | None) -> str:
    """Format an aware ISO timestamp in Paris; never guess a missing timezone."""
    if value is None or value == "":
        return "Non renseigné"
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except ValueError:
        return "Date invalide"
    if timestamp.utcoffset() is None:
        return "Fuseau non renseigné"
    return timestamp.astimezone(PARIS).strftime("%H:%M · %d/%m/%Y")
