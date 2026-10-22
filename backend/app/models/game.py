import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk

SOURCES = ("pgn", "chesscom", "lichess")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str | None] = mapped_column(String(64))
    # Source-independent content hash, so the same game imported twice (or via two
    # sources) is detected as a duplicate.
    fingerprint: Mapped[str] = mapped_column(String(64))
    pgn: Mapped[str] = mapped_column(Text)

    white: Mapped[str] = mapped_column(String(100))
    black: Mapped[str] = mapped_column(String(100))
    white_elo: Mapped[int | None] = mapped_column(SmallInteger)
    black_elo: Mapped[int | None] = mapped_column(SmallInteger)
    result: Mapped[str] = mapped_column(String(8))
    played_at: Mapped[date | None] = mapped_column(Date)
    time_control: Mapped[str | None] = mapped_column(String(32))
    opening_name: Mapped[str | None] = mapped_column(String(200))
    eco: Mapped[str | None] = mapped_column(String(8))
    event: Mapped[str | None] = mapped_column(String(200))
    ply_count: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = created_at_col()
    favorite: Mapped[bool] = mapped_column(default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(5000))
    # The analysis run already mined for training puzzles (so each review is scanned once).
    puzzles_scanned_run: Mapped[uuid.UUID | None] = mapped_column()
    # The review currently shown for this game; switched atomically when a run completes.
    current_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "analysis_runs.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_games_current_analysis",
        )
    )

    __table_args__ = (
        CheckConstraint("source IN ('pgn','chesscom','lichess')", name="ck_games_source"),
        CheckConstraint("result IN ('1-0','0-1','1/2-1/2','*')", name="ck_games_result"),
        Index("uq_games_owner_fingerprint", "owner_id", "fingerprint", unique=True),
        Index(
            "uq_games_owner_source_external",
            "owner_id",
            "source",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
        Index("ix_games_owner_played", "owner_id", "played_at"),
        Index("ix_games_owner_created", "owner_id", "created_at"),
    )


class GameTag(Base):
    """A short label the owner put on a game (compared case-insensitively, stored lower-case)."""

    __tablename__ = "game_tags"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(30), primary_key=True)


class GameMoveNote(Base):
    """The owner's note on one move of a game (ply 1 = White's first move)."""

    __tablename__ = "game_move_notes"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    ply: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    text: Mapped[str] = mapped_column(String(2000))
