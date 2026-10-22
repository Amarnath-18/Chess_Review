from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, session_user
from app.config import get_settings
from app.models.user import User
from app.services import invites
from app.services.ratelimit import SlidingWindow

router = APIRouter(prefix="/api/access", tags=["access"])

ATTEMPTS = SlidingWindow()
ATTEMPT_LIMIT = 10  # wrong or right, per address
ATTEMPT_WINDOW = 600.0


class AccessOut(BaseModel):
    required: bool  # this server asks for an invite code
    unlocked: bool  # this browser has one that works (always true when not required)
    label: str | None = None  # whose invite it is


class CodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=200)


def _status(db: Session, user: User) -> AccessOut:
    if not get_settings().access_required:
        return AccessOut(required=False, unlocked=True)
    invite = invites.invite_for(db, user)
    ok = invites.is_active(invite)
    return AccessOut(required=True, unlocked=ok, label=invite.label if ok and invite else None)


@router.get("", response_model=AccessOut)
def access_status(user: User = Depends(session_user), db: Session = Depends(get_db)):
    return _status(db, user)


@router.post("", response_model=AccessOut)
def unlock(
    body: CodeIn,
    request: Request,
    user: User = Depends(session_user),
    db: Session = Depends(get_db),
):
    """Unlock this browser with an invite code. Attempts are limited per address."""
    ip = request.client.host if request.client else "unknown"
    if not ATTEMPTS.allow(ip, ATTEMPT_LIMIT, ATTEMPT_WINDOW):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a few minutes.",
            headers={"Retry-After": str(ATTEMPTS.retry_after(ip, ATTEMPT_WINDOW))},
        )
    if invites.redeem(db, user, body.code) is None:
        raise HTTPException(status_code=403, detail="That code is not valid.")
    return _status(db, user)
