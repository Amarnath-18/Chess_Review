import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BatchFilter(BaseModel):
    """The same filters as the games list."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(None, max_length=100)
    source: Literal["pgn", "chesscom", "lichess"] | None = None
    result: Literal["1-0", "0-1", "1/2-1/2", "*"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    favorite: bool | None = None
    tag: str | None = Field(None, max_length=30)


class BatchRequest(BaseModel):
    """Pick games by id, or by the history filters. Settings default to the person's own."""

    model_config = ConfigDict(extra="forbid")

    game_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    filter: BatchFilter | None = None
    depth: int | None = Field(None, ge=1)
    nodes: int | None = Field(None, ge=1)
    multipv: int | None = Field(None, ge=1)
    # True (the default): leave out games that already have a review.
    only_unanalyzed: bool = True


class BatchEstimateOut(BaseModel):
    games: int  # how many would be analyzed
    skipped: int  # left out because they cannot be analyzed with these settings
    positions: int
    seconds: float | None
    seconds_low: float | None
    seconds_high: float | None
    too_many: bool  # more than one batch may hold
    max_games: int
    calibrated_from_runs: int


class BatchItemOut(BaseModel):
    game_id: uuid.UUID
    white: str
    black: str
    state: Literal["pending", "queued", "done", "failed", "skipped", "cancelled"]
    message: str | None
    progress_done: int | None = None  # for the game being analyzed right now
    progress_total: int | None = None


class BatchOut(BaseModel):
    id: uuid.UUID
    status: Literal["running", "completed", "cancelled"]
    params: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None
    total: int
    counts: dict[str, int]
    items: list[BatchItemOut]
