"""Privacy controls: delete my data."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.game import Game
from app.models.user import User
from app.schemas.settings import DeletedOut
from app.services.sessions import COOKIE_NAME

router = APIRouter(prefix="/api/me", tags=["privacy"])


@router.delete("/games", response_model=DeletedOut)
def delete_all_my_games(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete every saved game with its analyses and jobs. The session and settings stay."""
    result = db.execute(delete(Game).where(Game.owner_id == user.id))
    db.commit()
    return DeletedOut(deleted=result.rowcount or 0)


@router.delete("", status_code=204)
def delete_everything(
    response: Response, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Delete this anonymous user completely: games, analyses, jobs, settings and sessions."""
    db.delete(user)  # the database cascades to everything the user owns
    db.commit()
    out = Response(status_code=204)
    out.delete_cookie(COOKIE_NAME, path="/")
    return out
