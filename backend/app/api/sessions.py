import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import get_settings
from app.services.ratelimit import new_sessions
from app.services.sessions import (
    COOKIE_NAME,
    create_session,
    resolve_session,
    session_lifetime,
)

router = APIRouter(prefix="/api/session", tags=["session"])


class SessionOut(BaseModel):
    user_id: uuid.UUID
    new: bool
    retention_days: int


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(session_lifetime().total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


@router.post("", response_model=SessionOut)
def start_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """Idempotent: returns the current anonymous user, creating one if needed."""
    retention = get_settings().retention_days
    existing = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if existing is not None:
        return SessionOut(user_id=existing[0].id, new=False, retention_days=retention)
    ip = request.client.host if request.client else "unknown"
    if not new_sessions.allow(ip, get_settings().sessions_per_ip_per_hour, 3600):
        raise HTTPException(
            status_code=429,
            detail="Too many new sessions from this address. Please try again later.",
            headers={"Retry-After": str(new_sessions.retry_after(ip, 3600))},
        )
    user, token, _ = create_session(db)
    _set_cookie(response, token)
    return SessionOut(user_id=user.id, new=True, retention_days=retention)
