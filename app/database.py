"""Database connection setup: the engine, the session factory and get_db()."""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./calibrations.db"


class Base(DeclarativeBase):
    """Parent class of every model. create_all() uses it to find the tables to create."""


def make_engine(url: str | None = None, **kwargs) -> Engine:
    """Build a SQLite engine.

    Uses the url argument if given, then the DATABASE_URL environment variable,
    then a calibrations.db file in the folder the server is started from. The
    tests pass "sqlite://" to get a throwaway in-memory database.
    """
    url = url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # FastAPI runs plain `def` endpoints on a pool of worker threads, and SQLite
    # normally refuses to be used from any thread but the one that opened it.
    kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        # SQLite reads FOREIGN KEY clauses but ignores them unless this is
        # switched on, and it has to be switched on for every connection.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = make_engine()
# expire_on_commit=False: after a commit, keep the objects' values instead of
# reloading them from the database the next time they are read. The endpoints
# commit and then return the object, so the default would cost an extra query.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    """Give each request its own session and close it when the request ends."""
    with SessionLocal() as db:
        yield db
