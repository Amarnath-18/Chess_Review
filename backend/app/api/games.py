import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.user import User
from app.schemas.analysis import JobOut
from app.schemas.games import GameDetail, GameList, MoveOut
from app.services import games as svc

router = APIRouter(prefix="/api/games", tags=["games"])


def _owned(db: Session, user: User, game_id: uuid.UUID):
    game = svc.get_owned_game(db, user.id, game_id)
    if game is None:
        # 404 (not 403) so ids belonging to other users are indistinguishable from missing ones.
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("", response_model=GameList)
def list_games(
    q: str | None = Query(None, max_length=100),
    source: Literal["pgn", "chesscom", "lichess"] | None = None,
    result: Literal["1-0", "0-1", "1/2-1/2", "*"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    filters = svc.GameFilters(q, source, result, date_from, date_to)
    items, total = svc.list_games(db, user.id, filters, page, page_size)
    return GameList(
        items=svc.to_game_out(db, items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{game_id}", response_model=GameDetail)
def get_game(game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)):
    game = _owned(db, user, game_id)
    start_fen, moves = svc.replay_moves(game)
    base = svc.to_game_out(db, [game])[0].model_dump()
    job = svc.latest_jobs(db, [game.id]).get(game.id)
    return GameDetail(
        **base,
        pgn=game.pgn,
        start_fen=start_fen,
        moves=[MoveOut(**m) for m in moves],
        latest_job=JobOut.model_validate(job) if job else None,
    )


@router.delete("/{game_id}", status_code=204)
def delete_game(
    game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    svc.delete_game(db, _owned(db, user, game_id))
    return Response(status_code=204)
