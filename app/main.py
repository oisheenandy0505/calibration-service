"""HTTP layer: read the request, call the service, shape the response."""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import service
from app.database import Base, engine, get_db
from app.schemas import CalibrationCreate, CalibrationOut, MembershipOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs once at startup. create_all only creates tables that are missing; it
    # does not change existing ones, so a schema change needs a migration tool
    # (e.g. Alembic) or deleting calibrations.db. Left out to keep this small.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Calibration Service",
    description="Manage hardware calibrations and the tags that group them over time.",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
def root():
    """Opening the bare address would otherwise show a 404, so go to the docs."""
    return RedirectResponse(url="/docs")


# The service raises its own exceptions; these handlers pick the HTTP status.
@app.exception_handler(RequestValidationError)
def validation_error_handler(_request, exc: RequestValidationError):
    # FastAPI's default 422 body echoes the rejected input. For a value like
    # NaN that can't be written as JSON, so the "bad request" became a 500.
    # Keep only where the problem is, the message and the error type.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(service.NotFoundError)
def not_found_handler(_request, exc: service.NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(service.InvalidInputError)
def invalid_input_handler(_request, exc: service.InvalidInputError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# Plain `def`, not `async def`: the SQLAlchemy session is synchronous, and
# FastAPI runs plain `def` endpoints in a thread pool so they don't block others.
router = APIRouter(prefix="/calibrations", tags=["calibrations"])


@router.post("", response_model=CalibrationOut, status_code=201)
def create_calibration(body: CalibrationCreate, db: Session = Depends(get_db)):
    """Create a calibration. The server assigns `id` and `created_at`."""
    return service.create_calibration(db, body)


@router.get("", response_model=list[CalibrationOut])
def list_calibrations(
    username: str | None = Query(None, description="Exact match on user."),
    calibration_type: str | None = Query(None, description="Exact match on type."),
    created_after: datetime | None = Query(
        None, description="Created at or after this time (inclusive). Naive times are UTC."
    ),
    created_before: datetime | None = Query(
        None, description="Created strictly before this time (exclusive). Naive times are UTC."
    ),
    tag: str | None = Query(None, description="Only calibrations in this tag (right now by default)."),
    tag_as_of: datetime | None = Query(
        None, description="With `tag`: only calibrations that were in the tag at this instant."
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Search by any combination of user, time range, type and tag, newest first."""
    return service.list_calibrations(
        db,
        username=username,
        calibration_type=calibration_type,
        created_after=created_after,
        created_before=created_before,
        tag=tag,
        tag_as_of=tag_as_of,
        limit=limit,
        offset=offset,
    )


@router.get("/{calibration_id}", response_model=CalibrationOut)
def get_calibration(calibration_id: int, db: Session = Depends(get_db)):
    return service.get_calibration(db, calibration_id)


# `{tag:path}` lets a tag contain slashes (e.g. "fab/lot-7"). Without it the
# first slash would end the match and the route would 404.
@router.put(
    "/{calibration_id}/tags/{tag:path}",
    response_model=MembershipOut,
    status_code=201,
    responses={200: {"model": MembershipOut, "description": "Already in the tag; existing membership returned."}},
)
def add_to_tag(calibration_id: int, tag: str, response: Response, db: Session = Depends(get_db)):
    """Add a calibration to a tag.

    201 when a new membership is created, 200 (same body) if it was already in the tag.
    """
    membership, created = service.add_to_tag(db, calibration_id, tag)
    if not created:
        response.status_code = 200
    return membership


@router.delete("/{calibration_id}/tags/{tag:path}", status_code=204)
def remove_from_tag(calibration_id: int, tag: str, db: Session = Depends(get_db)):
    """Remove a calibration from a tag.

    204 whether or not it was in the tag; 404 only if the calibration doesn't
    exist. The membership is closed, not deleted, so history is kept.
    """
    service.remove_from_tag(db, calibration_id, tag)
    return Response(status_code=204)


@router.get("/{calibration_id}/tags", response_model=list[MembershipOut])
def get_calibration_tags(
    calibration_id: int,
    as_of: datetime | None = Query(None, description="Tags the calibration had at this instant."),
    include_history: bool = Query(False, description="Return every membership ever, including removed."),
    db: Session = Depends(get_db),
):
    """List current tags, tags at a given time, or the full membership history."""
    return service.get_tags_for_calibration(db, calibration_id, as_of, include_history)


app.include_router(router)
