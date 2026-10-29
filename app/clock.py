"""The one place the app reads the current time.

Anything that needs "now" calls utcnow() from here. The tests replace this one
function with a fake clock that only moves when the test says so, so a test about
what was in a tag an hour ago does not have to wait an hour.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    # Timezone-aware on purpose. Every timestamp in this service is UTC, and a
    # naive datetime would silently be read as local time by whoever got it next.
    return datetime.now(timezone.utc)
