"""The seed script, plus the rules the database enforces on its own.

The second half talks to the database directly instead of going through the
API. It checks that the foreign key, the check constraint and the partial
unique index reject bad rows even if the application code had a bug.
"""
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Calibration, TagMembership
from app.seed import BASELINE, PRESSURE, seed
from tests.conftest import T0


# ---- seed -----------------------------------------------------------------
def test_seed_loads_sample_data_once(client, session_factory):
    with session_factory() as db:
        assert seed(db, now=T0) == 15
        assert seed(db, now=T0) == 0  # second run is a no-op
        assert db.query(Calibration).count() == 15

    body = client.get("/calibrations", params={"limit": 200}).json()
    assert len(body) == 15
    assert {i["username"] for i in body} == {"alice", "bob", "charlie", "dana"}


def test_seed_tag_history_supports_time_travel(client, session_factory):
    with session_factory() as db:
        seed(db, now=T0)
    start = T0 - timedelta(minutes=60)

    def baseline_at(minutes):
        items = client.get(
            "/calibrations",
            params={"tag": BASELINE, "tag_as_of": (start + timedelta(minutes=minutes)).isoformat()},
        ).json()
        return {i["id"] for i in items}

    assert baseline_at(6) == set()
    assert baseline_at(8) == {1, 2, 3}  # before the swap
    assert baseline_at(10) == {2, 3, 4}  # after calibration 1 was replaced by 4
    current = client.get("/calibrations", params={"tag": BASELINE}).json()
    assert {i["id"] for i in current} == {2, 3, 4}

    pressure = client.get("/calibrations", params={"tag": PRESSURE}).json()
    assert {i["calibration_type"] for i in pressure} == {"pressure"}


# ---- database-level guarantees --------------------------------------------
def make_calibration(db):
    calibration = Calibration(calibration_type="gain", value=1.0, username="a", created_at=T0)
    db.add(calibration)
    db.commit()
    return calibration


def test_database_rejects_two_open_memberships(session_factory):
    with session_factory() as db:
        cal = make_calibration(db)
        db.add(TagMembership(calibration_id=cal.id, tag="golden", added_at=T0))
        db.commit()
        db.add(TagMembership(calibration_id=cal.id, tag="golden", added_at=T0 + timedelta(hours=1)))
        with pytest.raises(IntegrityError):
            db.commit()


def test_database_allows_many_closed_stays_plus_one_open(session_factory):
    with session_factory() as db:
        cal = make_calibration(db)
        for hour in (0, 2, 4):
            db.add(
                TagMembership(
                    calibration_id=cal.id,
                    tag="golden",
                    added_at=T0 + timedelta(hours=hour),
                    removed_at=T0 + timedelta(hours=hour + 1),
                )
            )
        db.add(TagMembership(calibration_id=cal.id, tag="golden", added_at=T0 + timedelta(hours=6)))
        db.commit()  # must not raise


def test_database_rejects_membership_for_missing_calibration(session_factory):
    with session_factory() as db:
        db.add(TagMembership(calibration_id=12345, tag="golden", added_at=T0))
        with pytest.raises(IntegrityError):
            db.commit()


def test_database_rejects_removal_before_addition(session_factory):
    with session_factory() as db:
        cal = make_calibration(db)
        db.add(
            TagMembership(
                calibration_id=cal.id,
                tag="golden",
                added_at=T0 + timedelta(hours=1),
                removed_at=T0,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()




# ---- real concurrency: stays must never overlap --------------------------------
