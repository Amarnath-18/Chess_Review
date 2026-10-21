import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRequest(BaseModel):
    """Omit both limits to use the server default depth."""

    depth: int | None = Field(None, ge=1)
    nodes: int | None = Field(None, ge=1)
    # Engine lines per position (the server caps this at MAX_MULTIPV). Two or more are needed
    # for the Great / Brilliant labels.
    multipv: int = Field(3, ge=1)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    game_id: uuid.UUID
    status: Literal["queued", "running", "completed", "failed"]
    progress_done: int
    progress_total: int
    attempts: int
    max_attempts: int
    error: str | None
    run_id: uuid.UUID | None
    params: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AnalysisStartOut(BaseModel):
    cached: bool
    job: JobOut | None
    run_id: uuid.UUID | None


class EvalOut(BaseModel):
    """White's perspective. At most one of cp / mate / terminal_result is set;
    all null means the evaluation is unavailable (not a draw)."""

    cp: int | None
    mate: int | None
    terminal_result: str | None
    display: str | None
    win_pct: float | None


class AltLineOut(BaseModel):
    move_uci: str | None
    move_san: str | None
    eval: EvalOut | None


class LineOut(BaseModel):
    rank: int  # 1 = engine's first choice
    move_uci: str | None
    move_san: str | None
    eval: EvalOut
    pv_san: list[str]


class PositionOut(BaseModel):
    ply: int
    fen: str
    eval: EvalOut
    depth: int | None
    best_move_uci: str | None  # the engine's preferred move from this position
    best_move_san: str | None
    pv_san: list[str]  # line 1 (kept for older clients; same as lines[0].pv_san)
    lines: list[LineOut]  # every engine line stored for this position, best first
    alt: AltLineOut | None  # second-best line (same as lines[1])
    played_move_uci: str | None  # the move that led to this position
    played_move_san: str | None
    classification: str | None
    loss_pct: float | None
    missed_win: bool
    is_sacrifice: bool


class RunOut(BaseModel):
    id: uuid.UUID
    status: str
    engine_name: str
    depth: int | None
    nodes: int | None
    multipv: int
    class_config_hash: str
    class_config: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None


class AnalysisOut(BaseModel):
    run: RunOut
    summary: dict[str, Any]
    positions: list[PositionOut]
