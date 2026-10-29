"""Request and response shapes (Pydantic). FastAPI uses them to validate input
and to build the /docs page."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CalibrationCreate(BaseModel):
    # str_strip_whitespace: " bob " and "bob" are the same user, and a name made
    # only of spaces fails min_length.
    # extra="forbid": a client that sends a field we don't accept (like
    # created_at, which only the server sets) gets a 422 and not a silent ignore.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    calibration_type: str = Field(min_length=1, max_length=64)
    # strict: only a real JSON number. Without it "1.5" and true would be
    # quietly converted. allow_inf_nan=False: NaN and Infinity aren't measurements.
    value: float = Field(strict=True, allow_inf_nan=False)
    username: str = Field(min_length=1, max_length=64)


class CalibrationOut(BaseModel):
    # from_attributes lets Pydantic read the fields straight off the SQLAlchemy object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    calibration_type: str
    value: float
    username: str
    created_at: datetime


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    calibration_id: int
    tag: str
    added_at: datetime
    # Null while the calibration is still in the tag.
    removed_at: datetime | None
