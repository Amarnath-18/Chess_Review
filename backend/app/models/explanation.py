import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class MoveExplanation(Base):
    """A checked explanation of one move of one review. Asking again is free: it is read from here."""

    __tablename__ = "move_explanations"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    ply: Mapped[int] = mapped_column(SmallInteger)
    level: Mapped[str] = mapped_column(String(12))
    model: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # "ai" | "fallback"
    motif: Mapped[str | None] = mapped_column(String(30))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (Index("uq_explanations_run_ply_level", "run_id", "ply", "level", unique=True),)


class LlmUsage(Base):
    """One row per explanation request that reached the model: feeds the daily limit and the
    `llm-usage` report (how often replies had to be retried or replaced by the plain fallback)."""

    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invite_codes.id", ondelete="SET NULL"), index=True
    )
    at: Mapped[datetime] = created_at_col()
    model: Mapped[str] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str] = mapped_column(String(10))  # valid | retried | fallback | failed

    __table_args__ = (Index("ix_llm_usage_at", "at"),)
