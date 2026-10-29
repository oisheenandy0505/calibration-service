"""Business logic. The routes in main.py only parse the request and shape the
response; the rules about calibrations and tags live here, so the seed script
and the tests can call them without going through HTTP."""
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.models import Calibration, TagMembership
from app.schemas import CalibrationCreate

MAX_TAG_LENGTH = 255  # matches the String(255) column


class NotFoundError(Exception):
    """The calibration doesn't exist. Becomes HTTP 404."""


class InvalidInputError(Exception):
    """The request is well-formed but the values don't make sense. Becomes HTTP 422."""


def to_utc(value: datetime) -> datetime:
    """Convert to UTC. A time with no timezone is assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_tag(raw: str) -> str:
    """Trim a tag and reject it if it is empty or too long.

    Case is kept, so "Gold" and "gold" are different tags. Every endpoint goes
    through here so tags are treated the same everywhere.
    """
    tag = raw.strip()
    if not tag:
        raise InvalidInputError("tag must not be empty")
    if len(tag) > MAX_TAG_LENGTH:
        raise InvalidInputError(f"tag must be at most {MAX_TAG_LENGTH} characters")
    return tag


def _active_conditions(as_of: datetime | None) -> list:
    """SQL conditions meaning "this stay is active at as_of" (or right now if None).

    A stay covers [added_at, removed_at): the calibration is in the tag at
    added_at and out of it at removed_at. Because the end is exclusive, a stay
    that ends at 10:00 and the next one that starts at 10:00 never both match
    the same instant.
    """
    if as_of is None:
        return [TagMembership.removed_at.is_(None)]
    return [
        TagMembership.added_at <= as_of,
        or_(TagMembership.removed_at.is_(None), TagMembership.removed_at > as_of),
    ]


# --------------------------------------------------------------------------
# calibrations
# --------------------------------------------------------------------------
def create_calibration(
    db: Session, data: CalibrationCreate, now: datetime | None = None
) -> Calibration:
    """Insert a calibration. `now` is only for the seed script and tests; the
    API never passes it, so a client can't choose its own created_at."""
    calibration = Calibration(
        calibration_type=data.calibration_type,
        value=data.value,
        username=data.username,
        created_at=now or clock.utcnow(),
    )
    db.add(calibration)
    db.commit()
    return calibration


def get_calibration(db: Session, calibration_id: int) -> Calibration:
    calibration = db.get(Calibration, calibration_id)
    if calibration is None:
        raise NotFoundError(f"calibration {calibration_id} not found")
    return calibration


# --------------------------------------------------------------------------
# tag membership
# --------------------------------------------------------------------------
def _find_open_membership(db: Session, calibration_id: int, tag: str) -> TagMembership | None:
    return db.scalars(
        select(TagMembership).where(
            TagMembership.calibration_id == calibration_id,
            TagMembership.tag == tag,
            TagMembership.removed_at.is_(None),
        )
    ).first()


def add_to_tag(
    db: Session, calibration_id: int, raw_tag: str, now: datetime | None = None
) -> tuple[TagMembership, bool]:
    """Add a calibration to a tag. Safe to repeat.

    Returns (membership, created). If the calibration is already in the tag,
    the existing stay is returned with created=False and nothing is written.
    """
    tag = normalize_tag(raw_tag)
    get_calibration(db, calibration_id)  # 404 if it doesn't exist

    existing = _find_open_membership(db, calibration_id, tag)
    if existing is not None:
        return existing, False

    membership = TagMembership(
        calibration_id=calibration_id, tag=tag, added_at=now or clock.utcnow()
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        # Two requests added the same tag at the same moment and the other one
        # got in first; the unique index rejected ours. The calibration is in
        # the tag either way, so return the winner's row.
        db.rollback()
        existing = _find_open_membership(db, calibration_id, tag)
        if existing is None:
            raise
        return existing, False
    return membership, True


def remove_from_tag(
    db: Session, calibration_id: int, raw_tag: str, now: datetime | None = None
) -> bool:
    """End the calibration's current stay in the tag. Returns True if one was ended.

    Removing from a tag it isn't in does nothing and returns False, so repeating
    a DELETE is harmless. An unknown calibration is still a 404.
    Nothing is deleted: removed_at is filled in and the row stays as history.
    """
    tag = normalize_tag(raw_tag)
    get_calibration(db, calibration_id)

    result = db.execute(
        update(TagMembership)
        .where(
            TagMembership.calibration_id == calibration_id,
            TagMembership.tag == tag,
            TagMembership.removed_at.is_(None),
        )
        .values(removed_at=now or clock.utcnow())
    )
    db.commit()
    return result.rowcount > 0


def get_tags_for_calibration(
    db: Session,
    calibration_id: int,
    as_of: datetime | None = None,
    include_history: bool = False,
) -> list[TagMembership]:
    """Tags of one calibration: current by default, a past instant with as_of,
    or every stay it has ever had with include_history."""
    if as_of is not None and include_history:
        raise InvalidInputError("as_of and include_history cannot be combined")
    get_calibration(db, calibration_id)

    stmt = select(TagMembership).where(TagMembership.calibration_id == calibration_id)
    if not include_history:
        stmt = stmt.where(*_active_conditions(to_utc(as_of) if as_of is not None else None))
    return list(db.scalars(stmt.order_by(TagMembership.tag, TagMembership.added_at)))


# --------------------------------------------------------------------------
# searching calibrations
# --------------------------------------------------------------------------
def list_calibrations(
    db: Session,
    *,
    username: str | None = None,
    calibration_type: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    tag: str | None = None,
    tag_as_of: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Calibration]:
    """Search calibrations. Every filter is optional; the ones given are ANDed.

    * created_after is inclusive, created_before is exclusive: [after, before).
    * tag alone: calibrations in the tag right now.
    * tag + tag_as_of: calibrations that were in the tag at that instant.
    Results are newest first.
    """
    if tag_as_of is not None and tag is None:
        raise InvalidInputError("tag_as_of requires tag")
    if created_after is not None:
        created_after = to_utc(created_after)
    if created_before is not None:
        created_before = to_utc(created_before)
    if created_after and created_before and created_after >= created_before:
        raise InvalidInputError("created_after must be earlier than created_before")

    stmt = select(Calibration)
    if username is not None:
        stmt = stmt.where(Calibration.username == username)
    if calibration_type is not None:
        stmt = stmt.where(Calibration.calibration_type == calibration_type)
    if created_after is not None:
        stmt = stmt.where(Calibration.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Calibration.created_at < created_before)

    if tag is not None:
        # A calibration can have several rows for the same tag (added, removed,
        # added again). Using IN means each calibration comes back once however
        # many rows match; a JOIN would repeat it.
        in_tag = select(TagMembership.calibration_id).where(
            TagMembership.tag == normalize_tag(tag),
            *_active_conditions(to_utc(tag_as_of) if tag_as_of is not None else None),
        )
        stmt = stmt.where(Calibration.id.in_(in_tag))

    # id breaks ties between calibrations created at the same instant, so the
    # order (and therefore the paging) is always the same.
    stmt = stmt.order_by(Calibration.created_at.desc(), Calibration.id.desc())
    return list(db.scalars(stmt.limit(limit).offset(offset)))
