from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.services.sessions import COOKIE_NAME, resolve_session


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The owner is derived only from the session cookie, never from client-supplied ids."""
    resolved = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if resolved is None:
        raise HTTPException(
            status_code=401, detail="No valid session. Call POST /api/session first."
        )
    return resolved[0]
