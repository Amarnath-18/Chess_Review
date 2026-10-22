import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PuzzleOut(BaseModel):
    """What the person sees before answering: the position only, never the solution."""

    id: uuid.UUID
    fen: str
    side_to_move: str  # "white" | "black"
    game_id: uuid.UUID
    ply: int
    box: int


class TrainOut(BaseModel):
    needs_names: bool  # no names or remembered accounts, so nothing can be attributed to the person
    games_looked_at: int  # reviews newly mined by this call
    new_puzzles: int
    total: int
    due: int
    mastered: int
    next: PuzzleOut | None


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uci: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class AnswerOut(BaseModel):
    correct: bool
    best_uci: str
    best_san: str | None
    played_uci: str
    played_san: str | None  # what was actually played in the game
    line_san: list[str]  # the engine's line, for the reveal
    game_id: uuid.UUID
    ply: int
    box: int
    due_at: datetime
    due: int  # puzzles waiting now, after this answer
