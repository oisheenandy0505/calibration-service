"""Load the sample calibrations (plus a little tag history) into the database.

    python -m app.seed

Safe to run twice: it does nothing if calibrations already exist.

The 15 calibrations come from seed_data.json, which is the table in the
assignment PDF. They are not all created at the same instant. Each gets its own
created_at, two minutes apart, and the last one lands 30 minutes before the
moment the script runs (the first is 58 minutes before). That gives the time
filters something to work with. A small made-up tag history is added on top of
that, so the as-of queries have something to show too.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock, service
from app.database import Base, SessionLocal, engine
from app.models import Calibration
from app.schemas import CalibrationCreate

SEED_FILE = Path(__file__).parent / "seed_data.json"

BASELINE = "production-baseline"
PRESSURE = "pressure-check"

# (minutes after start, action, 1-based row number in seed_data.json, tag)
# "start" is the point 60 minutes before the script runs. Calibration N is
# created at minute 2*N, so every event below happens after the calibration it
# touches already exists. The story: calibrations 1-3 become the production
# baseline at minute 7. At minute 9, calibration 1 is replaced by calibration
# 4 (same type and user, new value). So "who was in the baseline at minute 8"
# and "who is in it now" give different answers, which is the point of this data.
# Calibrations 9 and 14 get the pressure-check tag later on.
TAG_EVENTS = [
    (7, "add", 1, BASELINE),
    (7, "add", 2, BASELINE),
    (7, "add", 3, BASELINE),
    (9, "remove", 1, BASELINE),
    (9, "add", 4, BASELINE),
    (19, "add", 9, PRESSURE),
    (29, "add", 14, PRESSURE),
]


def seed(db: Session, now: datetime | None = None) -> int:
    """Insert the sample data. Returns how many calibrations were created.

    The now argument is only so the tests can pin the starting time. When the
    database already has any calibration at all, nothing is inserted and 0 is
    returned.
    """
    if db.scalar(select(func.count()).select_from(Calibration)):
        return 0

    start = (now or clock.utcnow()) - timedelta(minutes=60)
    rows = json.loads(SEED_FILE.read_text())

    # Remember the database id of each row, in file order, so TAG_EVENTS can
    # refer to "row 4" and get the right calibration even if the table
    # already had ids used up.
    ids = []
    for number, row in enumerate(rows, start=1):
        created = service.create_calibration(
            db, CalibrationCreate(**row), now=start + timedelta(minutes=2 * number)
        )
        ids.append(created.id)

    for minute, action, row_number, tag in TAG_EVENTS:
        when = start + timedelta(minutes=minute)
        calibration_id = ids[row_number - 1]
        # The same service functions the API uses, with `now` set to the
        # event's own time instead of the real clock.
        if action == "add":
            service.add_to_tag(db, calibration_id, tag, now=when)
        else:
            service.remove_from_tag(db, calibration_id, tag, now=when)

    return len(ids)


if __name__ == "__main__":
    # The server creates tables when it starts, but this script can run
    # before the server ever has, so it creates them itself.
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        created = seed(session)
    print(f"Seeded {created} calibrations." if created else "Database already has data; nothing to do.")
