import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.games import ExternalSource, PreviewGameOut


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ExternalSource
    username: str = Field(min_length=1, max_length=40)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: ExternalSource
    username: str
    created_at: datetime
    last_checked_at: datetime | None


class NewGamesOut(BaseModel):
    """What a check found: the recent games not yet saved, ready to import with /api/imports/commit."""

    source_id: uuid.UUID
    source: ExternalSource
    username: str
    new_games: list[PreviewGameOut]
    checked: int  # how many recent games were looked at
    already_saved: int
    cannot_import: int  # new but unsupported (e.g. a variant)
    note: str | None
    skipped_archives: int
