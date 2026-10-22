import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.explanation import MoveExplanation
from app.models.user import User
from app.services import games as games_svc
from app.services.explain import service

router = APIRouter(prefix="/api/games", tags=["explain"])


class ExplanationOut(BaseModel):
    ply: int
    text: str
    source: str  # "ai": written by the model and checked against the engine facts; "fallback": built from the facts
    motif: str | None
    model: str
    level: str
    cached: bool
    remaining_today: int
    created_at: datetime


class ExplanationsOut(BaseModel):
    items: list[ExplanationOut]
    remaining_today: int


def _out(row: MoveExplanation, cached: bool, remaining: int) -> ExplanationOut:
    return ExplanationOut(
        ply=row.ply,
        text=row.text,
        source=row.source,
        motif=row.motif,
        model=row.model,
        level=row.level,
        cached=cached,
        remaining_today=remaining,
        created_at=row.created_at,
    )


def _owned(db: Session, user: User, game_id: uuid.UUID):
    game = games_svc.get_owned_game(db, user.id, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("/{game_id}/explanations", response_model=ExplanationsOut)
def list_explanations(
    game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Explanations already made for this game's current review (at the person's level)."""
    game = _owned(db, user, game_id)
    remaining = service.remaining_today(db, user)
    if game.current_analysis_id is None:
        return ExplanationsOut(items=[], remaining_today=remaining)
    rows = service.stored(db, game.current_analysis_id, service.level_for(user))
    return ExplanationsOut(items=[_out(r, True, remaining) for r in rows], remaining_today=remaining)


@router.post("/{game_id}/explain/{ply}", response_model=ExplanationOut)
def explain_move(
    game_id: uuid.UUID, ply: int, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Explain one move. Needs the person's opt-in, a configured model and an analyzed game. The
    reply is checked against the engine facts and cached, so asking again is instant and free."""
    game = _owned(db, user, game_id)
    try:
        row, cached = service.explain_ply(db, user, game, ply)
    except service.ExplainError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status_code, detail=exc.message, headers=headers) from exc
    return _out(row, cached, service.remaining_today(db, user))
