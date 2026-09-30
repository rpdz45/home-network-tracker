"""Project-wide exception types."""


class NetTrackerError(Exception):
    """Base class for expected, user-facing errors."""


class ConfigError(NetTrackerError):
    """The configuration is missing, unreadable or invalid."""


class DatabaseError(NetTrackerError):
    """A database operation failed."""
