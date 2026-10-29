"""Shared pytest setup. Every test file gets these fixtures automatically.

Each test runs against its own empty in-memory SQLite database and a fake clock,
so tests don't affect each other and don't depend on the real time or on a
calibrations.db file lying around.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import clock
from app.database import Base, get_db, make_engine
from app.main import app

# A fixed starting time. Tests express every other time relative to it (T0 plus
# some minutes), which keeps the expected values in assertions easy to read.
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    """Callable stand-in for app.clock.utcnow that only moves when told to.

    Calling it returns the current fake time, the same as clock.utcnow() does.
    A test moves time forward with advance(), so "an hour later" takes no
    waiting and always gives the same timestamps.
    """

    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)
        return self.now


@pytest.fixture
def engine():
    # An in-memory SQLite database exists only inside the connection that
    # created it. With the normal pool, a second connection would open a
    # different, empty database and the tables would seem to be missing.
    # StaticPool keeps one shared connection, so every session sees the same
    # database. Each test gets a fresh engine and therefore a fresh database.
    eng = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    # Same settings as the real SessionLocal in app/database.py, but bound to the
    # test engine.
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def fake_clock(monkeypatch):
    # monkeypatch undoes the replacement when the test ends. The services call
    # clock.utcnow() through the module, so swapping the attribute here is
    # enough to change the time everywhere in the app.
    fake = FakeClock()
    monkeypatch.setattr(clock, "utcnow", fake)
    return fake


@pytest.fixture
def client(session_factory, fake_clock):
    # Make the app use the test database instead of the real one. Every request
    # gets a session from the test factory and closes it afterwards, just as
    # get_db does in production.
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # TestClient is deliberately not used as a context manager. Doing so would
    # run the app's startup hook, which creates tables in the real
    # calibrations.db file. The tables already exist in the in-memory database.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def create_cal(client):
    """Factory: create a calibration through the API and return its JSON.

    Going through POST /calibrations, and not inserting rows directly, means
    created_at comes from the fake clock exactly as it would in production.
    """

    def _create(username="alice", calibration_type="offset", value=1.0):
        response = client.post(
            "/calibrations",
            json={"calibration_type": calibration_type, "value": value, "username": username},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create
