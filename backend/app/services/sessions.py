"""Anonymous sessions: an opaque random token in a cookie; only its hash is stored."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.base import utcnow
from app.models.user import User, UserSession

COOKIE_NAME = "sid"
_TOUCH_INTERVAL = timedelta(hours=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_lifetime() -> timedelta:
    return timedelta(days=get_settings().retention_days)


def create_session(db: Session) -> tuple[User, str, UserSession]:
    user = User()
    db.add(user)
    db.flush()
    token = secrets.token_urlsafe(32)
    sess = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + session_lifetime(),
    )
    db.add(sess)
    db.commit()
    return user, token, sess


def resolve_session(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    """Return the owner for a valid, unexpired token; slide the expiry on use."""
    if not token:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if sess is None:
        return None
    now = utcnow()
    if sess.expires_at <= now:
        return None
    user = db.get(User, sess.user_id)
    if user is None:
        return None
    if now - user.last_seen_at > _TOUCH_INTERVAL:
        user.last_seen_at = now
        sess.expires_at = now + session_lifetime()
        db.commit()
    return user, sess
