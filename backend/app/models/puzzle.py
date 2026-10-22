import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class Puzzle(Base):
    """A position from one of the owner's own games where they went wrong and the engine's best
    move was clearly better than every alternative. Scheduled with Leitner boxes."""

    __tablename__ = "puzzles"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    ply: Mapped[int] = mapped_column(SmallInteger)  # the move that was played (1 = White's first)
    fen: Mapped[str] = mapped_column(String(100))  # the position before that move
    best_uci: Mapped[str] = mapped_column(String(8))
    accepted_uci: Mapped[list[str]] = mapped_column(ARRAY(Text))  # answers counted as correct
    played_uci: Mapped[str] = mapped_column(String(8))
    loss_pct: Mapped[float] = mapped_column(Float)
    line: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"pv": [uci...]} for the reveal
    box: Mapped[int] = mapped_column(SmallInteger, default=1)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        Index("uq_puzzles_game_ply", "game_id", "ply", unique=True),
        Index("ix_puzzles_owner_due", "owner_id", "due_at"),
    )


class PuzzleAttempt(Base):
    __tablename__ = "puzzle_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    puzzle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("puzzles.id", ondelete="CASCADE"), index=True
    )
    answered_uci: Mapped[str] = mapped_column(String(8))
    correct: Mapped[bool]
    at: Mapped[datetime] = created_at_col()
