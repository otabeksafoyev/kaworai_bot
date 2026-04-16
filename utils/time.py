"""
Time helpers.

`datetime.utcnow()` is deprecated from Python 3.12 onwards because it returns a
naive datetime despite sourcing a UTC value. The recommended replacement,
`datetime.now(timezone.utc)`, returns a *tz-aware* datetime — which would break
every comparison and persistence site in this codebase, because all `DateTime`
columns in `database/models.py` are declared without `timezone=True` and store
naive values.

This module exposes a drop-in replacement that keeps the naive-UTC semantics
while avoiding the deprecation warning. When the DB is eventually migrated to
tz-aware `DateTime(timezone=True)` columns, remove the `.replace(tzinfo=None)`
call here in one place rather than touching every caller.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a *naive* :class:`datetime`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
