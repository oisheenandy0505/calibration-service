"""Database tables.

calibrations      One row per calibration. Never edited after it is created.

tag_memberships   One row per "stay" of a calibration in a tag. A stay starts at
                  added_at and ends at removed_at. While removed_at is NULL the
                  calibration is still in the tag.

Removing a calibration from a tag does not delete the row. It fills in
removed_at, and adding the calibration again later creates a new row. Because
every stay keeps its start and its end, we can answer "what was in tag X at
time T?" as well as "what is in tag X now?".
"""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


class UTCDateTime(TypeDecorator):
    """A DateTime column that is always timezone-aware UTC in Python.

    SQLite has no timezone support. It stores plain text and returns naive
    datetimes. Since we compare times in queries, everything stored needs to be
    UTC. This converts to UTC on the way in and puts the UTC label back on the
    way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True  # tells SQLAlchemy it may cache queries that use this type

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to the database; use timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Calibration(Base):
    __tablename__ = "calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed because these are the fields people filter on.
    calibration_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)
    username: Mapped[str] = mapped_column(String(64), index=True)
    # Set by the server when the row is created. The client can't choose it.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class TagMembership(Base):
    __tablename__ = "tag_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    calibration_id: Mapped[int] = mapped_column(
        ForeignKey("calibrations.id", ondelete="CASCADE"), index=True
    )
    tag: Mapped[str] = mapped_column(String(255))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # NULL while the calibration is still in the tag.
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        # A stay can't end before it starts.
        CheckConstraint(
            "removed_at IS NULL OR removed_at >= added_at",
            name="ck_membership_interval_valid",
        ),
        # A calibration can only be in a given tag once at a time. This index
        # only covers rows where removed_at IS NULL, so any number of finished
        # stays for the same tag are fine. Having the database enforce this
        # means it holds even if two requests arrive together, which a
        # "check first, then insert" in Python can't promise.
        Index(
            "uq_membership_one_open_stay",
            "calibration_id",
            "tag",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
        ),
        # Speeds up "which calibrations are in this tag".
        Index("ix_membership_tag_added_at", "tag", "added_at"),
    )
