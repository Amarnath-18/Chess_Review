"""Deleting data nobody has visited for a while (privacy: FR-09, NFR-03)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.game import Game
from app.models.user import User, UserSession


@dataclass
class PurgeResult:
    users: int = 0
    games: int = 0
    expired_sessions: int = 0


def purge_inactive(
    db: Session, retention_days: int, now: datetime | None = None
) -> PurgeResult:
    """Delete anonymous users not seen for `retention_days`, with everything they own (games,
    analyses, jobs, sessions: the database cascades), plus expired session rows.
    retention_days <= 0 turns the purge off. Commits."""
    if retention_days <= 0:
        return PurgeResult()
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)

    expired = db.execute(delete(UserSession).where(UserSession.expires_at < now)).rowcount or 0
    stale_users = select(User.id).where(User.last_seen_at < cutoff)
    games = (
        db.scalar(select(func.count()).select_from(Game).where(Game.owner_id.in_(stale_users)))
        or 0
    )
    users = db.execute(delete(User).where(User.last_seen_at < cutoff)).rowcount or 0
    db.commit()
    return PurgeResult(users=users, games=games, expired_sessions=expired)
