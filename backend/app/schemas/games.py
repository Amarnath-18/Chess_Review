import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import JobOut
from app.services.importing.pgn import MAX_PGN_BYTES


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    external_id: str | None
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    played_at: date | None
    time_control: str | None
    opening_name: str | None
    eco: str | None
    event: str | None
    ply_count: int
    created_at: datetime
    # none | queued | running | completed | failed. A game with a saved review and a failed
    # re-analysis is still "completed": the old review stays valid.
    analysis_status: Literal["none", "queued", "running", "completed", "failed"]
    has_analysis: bool


class MoveOut(BaseModel):
    ply: int
    san: str
    uci: str
    fen: str  # position after this move


class GameDetail(GameOut):
    pgn: str
    start_fen: str
    moves: list[MoveOut]
    latest_job: JobOut | None = None


class GameList(BaseModel):
    items: list[GameOut]
    total: int
    page: int
    page_size: int


class PgnImportRequest(BaseModel):
    pgn_text: str = Field(max_length=MAX_PGN_BYTES)


class ImportErrorOut(BaseModel):
    index: int
    message: str


class DuplicateOut(BaseModel):
    index: int
    game: GameOut


class ImportResult(BaseModel):
    imported: list[GameOut]
    duplicates: list[DuplicateOut]
    errors: list[ImportErrorOut]


# ---- importing from Chess.com / Lichess ------------------------------------------------

ExternalSource = Literal["chesscom", "lichess"]


class PreviewRequest(BaseModel):
    source: ExternalSource
    username: str = Field(min_length=1, max_length=40)
    max_games: int = Field(20, ge=1, le=50)


class PreviewGameOut(BaseModel):
    external_id: str
    url: str | None
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    played_at: date | None
    time_control: str | None
    opening_name: str | None
    ply_count: int | None
    already_imported: bool
    importable: bool
    problem: str | None  # why a game cannot be imported


class PreviewOut(BaseModel):
    source: ExternalSource
    username: str
    games: list[PreviewGameOut]
    skipped_archives: int
    note: str | None


class CommitRequest(BaseModel):
    source: ExternalSource
    username: str = Field(min_length=1, max_length=40)
    external_ids: list[str] = Field(min_length=1, max_length=50)


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    username_hint: str | None = Field(None, max_length=40)
