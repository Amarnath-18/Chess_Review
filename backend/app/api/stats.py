from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.user import User
from app.services import stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def my_stats(user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    """Personal statistics over the person's own analyzed games. Small samples are flagged
    (`reliable: false`) and never described as weaknesses; see `min_games` / `min_moves`."""
    return stats.compute(db, user)
