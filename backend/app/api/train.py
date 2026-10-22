import uuid

import chess
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.puzzle import Puzzle
from app.models.user import User
from app.schemas.train import AnswerIn, AnswerOut, PuzzleOut, TrainOut
from app.services import identity, training
from app.services.analysis.store import pv_to_san, to_san

router = APIRouter(prefix="/api/train", tags=["train"])


def _puzzle_out(p: Puzzle) -> PuzzleOut:
    return PuzzleOut(
        id=p.id,
        fen=p.fen,
        side_to_move="white" if p.fen.split()[1] == "w" else "black",
        game_id=p.game_id,
        ply=p.ply,
        box=p.box,
    )


@router.get("", response_model=TrainOut)
def training_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Mines any new reviews for puzzles, then reports what is due and the next puzzle."""
    looked, created = training.mine(db, user)
    nxt = training.next_due(db, user.id)
    return TrainOut(
        needs_names=not identity.my_names(db, user),
        games_looked_at=looked,
        new_puzzles=created,
        next=_puzzle_out(nxt) if nxt else None,
        **training.counts(db, user.id),
    )


@router.post("/{puzzle_id}/answer", response_model=AnswerOut)
def answer_puzzle(
    puzzle_id: uuid.UUID,
    body: AnswerIn,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    puzzle = db.scalar(
        select(Puzzle).where(Puzzle.id == puzzle_id, Puzzle.owner_id == user.id)
    )
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    try:
        move = chess.Move.from_uci(body.uci)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Not a move.") from exc
    if move not in chess.Board(puzzle.fen).legal_moves:
        raise HTTPException(status_code=422, detail="That move is not legal in this position.")
    correct = training.answer(db, puzzle, body.uci)
    pv = (puzzle.line or {}).get("pv", [])
    return AnswerOut(
        correct=correct,
        best_uci=puzzle.best_uci,
        best_san=to_san(puzzle.fen, puzzle.best_uci),
        played_uci=puzzle.played_uci,
        played_san=to_san(puzzle.fen, puzzle.played_uci),
        line_san=pv_to_san(puzzle.fen, pv),
        game_id=puzzle.game_id,
        ply=puzzle.ply,
        box=puzzle.box,
        due_at=puzzle.due_at,
        due=training.counts(db, user.id)["due"],
    )
