import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class LinkedSource(Base):
    """A Chess.com or Lichess account the owner asked us to remember, so "check for new games"
    needs no typing. Only the public username is stored (no credentials)."""

    __tablename__ = "linked_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    username: Mapped[str] = mapped_column(String(30))  # as the person typed it
    username_key: Mapped[str] = mapped_column(String(30))  # lower-case, for the uniqueness rule
    created_at: Mapped[datetime] = created_at_col()
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source IN ('chesscom','lichess')", name="ck_sources_source"),
        # the same account twice (ignoring case) is one account
        Index("uq_sources_owner_account", "owner_id", "source", "username_key", unique=True),
    )
