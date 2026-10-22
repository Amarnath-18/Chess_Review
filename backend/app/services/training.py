"""The puzzle trainer: positions from the owner's own reviews where they went wrong.

A position becomes a puzzle only when (1) the mover is the person themself, (2) they made a
Mistake, Blunder or missed a win, and (3) the engine's first choice beat its second choice by a
clear margin, so the answer is unambiguous. Nothing is invented: every puzzle is a real position
from a saved review, with the engine lines stored at analysis time.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import chess
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisPosition
from app.models.base import utcnow
from app.models.game import Game
from app.models.puzzle import Puzzle, PuzzleAttempt
from app.models.user import User
from app.services import identity
from app.services.analysis.store import row_to_position
from app.services.classification.config import ClassificationConfig
from app.services.classification.score import win_pct_for

MIN_GAP = 10.0  # the best move must beat the second best by this many win% points
ACCEPT_WITHIN = 3.0  # other moves this close to the best also count as correct
MAX_PER_GAME = 3
GAMES_PER_SCAN = 100

# Leitner boxes: how long until a puzzle comes back after being solved (box -> interval)
INTERVALS = {
    1: timedelta(minutes=10),
    2: timedelta(days=1),
    3: timedelta(days=3),
    4: timedelta(days=7),
    5: timedelta(days=21),
}
MISS_INTERVAL = INTERVALS[1]


@dataclass
class Candidate:
    ply: int
    fen: str
    best_uci: str
    accepted: list[str]
    played_uci: str
    loss: float
    pv: list[str]


def find_candidates(rows: list[AnalysisPosition], color: str) -> list[Candidate]:
    """Puzzle positions in one review, for the side `color`. Pure apart from the rows."""
    config = ClassificationConfig()
    me = chess.WHITE if color == "white" else chess.BLACK
    out: list[Candidate] = []
    for k in range(1, len(rows)):
        after, before = rows[k], rows[k - 1]
        if after.played_move_uci is None or before.terminal_result is not None:
            continue
        if chess.Board(before.fen).turn != me:
            continue
        wrong = after.classification in ("mistake", "blunder") or after.missed_win
        if not wrong or (after.loss_pct or 0) < config.mistake_loss:
            continue
        lines = row_to_position(before).lines
        if len(lines) < 2 or not lines[0].pv:
            continue
        best_win = win_pct_for(lines[0].score, me)
        if best_win - win_pct_for(lines[1].score, me) < MIN_GAP:
            continue  # several moves are about as good: not a clear question
        best = lines[0].pv[0]
        if after.played_move_uci == best:
            continue
        accepted = [best] + [
            ln.pv[0]
            for ln in lines[1:]
            if ln.pv and best_win - win_pct_for(ln.score, me) <= ACCEPT_WITHIN
        ]
        out.append(
            Candidate(
                ply=k,
                fen=before.fen,
                best_uci=best,
                accepted=accepted,
                played_uci=after.played_move_uci,
                loss=after.loss_pct or 0.0,
                pv=list(lines[0].pv[:6]),
            )
        )
    out.sort(key=lambda c: -c.loss)
    return out[:MAX_PER_GAME]


def mine(db: Session, user: User) -> tuple[int, int]:
    """Create puzzles from reviews not mined yet. Returns (games looked at, puzzles created).
    Games where the person cannot be identified are skipped and tried again later."""
    names = identity.my_names(db, user)
    if not names:
        return 0, 0
    games = db.scalars(
        select(Game)
        .where(
            Game.owner_id == user.id,
            Game.current_analysis_id.is_not(None),
            (Game.puzzles_scanned_run.is_(None))
            | (Game.puzzles_scanned_run != Game.current_analysis_id),
        )
        .limit(GAMES_PER_SCAN)
    ).all()
    looked = created = 0
    now = utcnow()
    for game in games:
        color = identity.my_color(game, names)
        if color is None:
            continue
        rows = list(
            db.scalars(
                select(AnalysisPosition)
                .where(AnalysisPosition.run_id == game.current_analysis_id)
                .order_by(AnalysisPosition.ply)
            )
        )
        looked += 1
        for cand in find_candidates(rows, color):
            exists = db.scalar(
                select(Puzzle.id).where(Puzzle.game_id == game.id, Puzzle.ply == cand.ply)
            )
            if exists:
                continue
            db.add(
                Puzzle(
                    owner_id=user.id,
                    game_id=game.id,
                    ply=cand.ply,
                    fen=cand.fen,
                    best_uci=cand.best_uci,
                    accepted_uci=cand.accepted,
                    played_uci=cand.played_uci,
                    loss_pct=cand.loss,
                    line={"pv": cand.pv},
                    box=1,
                    due_at=now,
                )
            )
            created += 1
        game.puzzles_scanned_run = game.current_analysis_id
    db.commit()
    return looked, created


def next_due(db: Session, owner_id: uuid.UUID, now: datetime | None = None) -> Puzzle | None:
    return db.scalar(
        select(Puzzle)
        .where(Puzzle.owner_id == owner_id, Puzzle.due_at <= (now or utcnow()))
        .order_by(Puzzle.due_at, Puzzle.created_at)
        .limit(1)
    )


def counts(db: Session, owner_id: uuid.UUID, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    total = db.scalar(select(func.count()).select_from(Puzzle).where(Puzzle.owner_id == owner_id))
    due = db.scalar(
        select(func.count())
        .select_from(Puzzle)
        .where(Puzzle.owner_id == owner_id, Puzzle.due_at <= now)
    )
    mastered = db.scalar(
        select(func.count())
        .select_from(Puzzle)
        .where(Puzzle.owner_id == owner_id, Puzzle.box >= 4)
    )
    return {"total": total or 0, "due": due or 0, "mastered": mastered or 0}


def answer(db: Session, puzzle: Puzzle, uci: str, now: datetime | None = None) -> bool:
    """Judge an answer and reschedule: right moves the puzzle up a box (it returns later),
    wrong sends it back to box 1 (it returns soon). Commits."""
    now = now or utcnow()
    correct = uci in puzzle.accepted_uci
    if correct:
        puzzle.box = min(5, puzzle.box + 1)
        puzzle.due_at = now + INTERVALS[puzzle.box]
    else:
        puzzle.box = 1
        puzzle.due_at = now + MISS_INTERVAL
    db.add(PuzzleAttempt(puzzle_id=puzzle.id, answered_uci=uci, correct=correct, at=now))
    db.commit()
    return correct
