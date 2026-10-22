from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models.user import User
from app.services import invites
from app.services.sessions import COOKIE_NAME, resolve_session


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def session_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The user behind the session cookie (401 without one), before any invite check."""
    resolved = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if resolved is None:
        raise HTTPException(
            status_code=401, detail="No valid session. Call POST /api/session first."
        )
    return resolved[0]


def require_user(user: User = Depends(session_user), db: Session = Depends(get_db)) -> User:
    """The owner is derived only from the session cookie, never from client-supplied ids. On a
    private server (ACCESS_REQUIRED) the session must also have unlocked an active invite."""
    if get_settings().access_required and not invites.is_active(invites.invite_for(db, user)):
        raise HTTPException(
            status_code=403, detail="An invite code is needed to use this server."
        )
    return user
