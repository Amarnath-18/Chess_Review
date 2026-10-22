import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk

BATCH_STATUSES = ("running", "completed", "cancelled")
ITEM_STATES = ("pending", "queued", "done", "failed", "skipped", "cancelled")


class AnalysisBatch(Base):
    """"Analyze these games" as one unit. The worker's maintenance loop feeds its games into the
    ordinary job queue a few at a time, so a batch never floods the queue or starves other work."""

    __tablename__ = "analysis_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)  # depth / nodes / multipv, as for one game
    created_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','cancelled')", name="ck_batches_status"),
        # At most one running batch per person (enforced by the database, race-proof).
        Index(
            "uq_batches_one_running_per_owner",
            "owner_id",
            unique=True,
            postgresql_where="status = 'running'",
        ),
    )


class BatchGame(Base):
    __tablename__ = "batch_games"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_batches.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)
    state: Mapped[str] = mapped_column(String(10))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL")
    )
    message: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','queued','done','failed','skipped','cancelled')",
            name="ck_batch_games_state",
        ),
        Index("ix_batch_games_batch_state", "batch_id", "state"),
    )
