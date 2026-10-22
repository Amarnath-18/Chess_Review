import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk

RUN_STATUSES = ("running", "completed", "failed")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
CLASSIFICATIONS = ("brilliant", "great", "best", "good", "inaccuracy", "mistake", "blunder")


class AnalysisRun(Base):
    """One complete (or failed) analysis of a game under one set of settings.

    A game only exposes a review through games.current_analysis_id, which is switched
    in the same transaction that marks the run completed.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12))
    engine_name: Mapped[str] = mapped_column(String(100))
    limit_depth: Mapped[int | None] = mapped_column(SmallInteger)
    limit_nodes: Mapped[int | None] = mapped_column(Integer)
    multipv: Mapped[int] = mapped_column(SmallInteger)
    class_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    class_config_hash: Mapped[str] = mapped_column(String(16))
    cache_key: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_runs_status"),
        Index(
            "uq_runs_game_cache_completed",
            "game_id",
            "cache_key",
            unique=True,
            postgresql_where="status = 'completed'",
        ),
    )


class AnalysisPosition(Base):
    """Position after `ply` half-moves (ply 0 = start). All scores are White's perspective.

    score_cp / score_mate / terminal_result all NULL means "unavailable" (never 0).
    """

    __tablename__ = "analysis_positions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), primary_key=True
    )
    ply: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    fen: Mapped[str] = mapped_column(String(100))

    score_cp: Mapped[int | None] = mapped_column(Integer)
    score_mate: Mapped[int | None] = mapped_column(SmallInteger)
    terminal_result: Mapped[str | None] = mapped_column(String(8))
    win_pct: Mapped[float | None] = mapped_column(Float)
    depth_reached: Mapped[int | None] = mapped_column(SmallInteger)

    # NULL = no engine line (terminal / unavailable); [] = a line without a PV
    pv_uci: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # All engine lines, best first: [{"cp": int|None, "mate": int|None, "pv": [uci, ...]}, ...].
    # NULL on reviews made before multi-line support (the columns around it still hold lines 1-2).
    lines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    alt_score_cp: Mapped[int | None] = mapped_column(Integer)
    alt_score_mate: Mapped[int | None] = mapped_column(SmallInteger)
    alt_pv_uci: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    played_move_uci: Mapped[str | None] = mapped_column(String(8))
    played_move_san: Mapped[str | None] = mapped_column(String(16))
    classification: Mapped[str | None] = mapped_column(String(12))
    loss_pct: Mapped[float | None] = mapped_column(Float)
    missed_win: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_sacrifice: Mapped[bool] = mapped_column(default=False, server_default="false")

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(score_cp, score_mate, terminal_result) <= 1", name="ck_pos_one_score"
        ),
        CheckConstraint(
            "num_nonnulls(alt_score_cp, alt_score_mate) <= 1", name="ck_pos_one_alt_score"
        ),
        CheckConstraint(
            "classification IS NULL OR classification IN "
            "('brilliant','great','best','excellent','good','inaccuracy','mistake','blunder')",
            name="ck_pos_classification",
        ),
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, default=2)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    progress_done: Mapped[int] = mapped_column(SmallInteger, default=0)
    progress_total: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_status_created", "status", "created_at"),
        # At most one active job per game, enforced by the database (race-proof).
        Index(
            "uq_jobs_one_active_per_game",
            "game_id",
            unique=True,
            postgresql_where="status IN ('queued','running')",
        ),
    )
