from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import date

import chess
import chess.pgn
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisJob
from app.models.game import Game
from app.schemas.games import GameOut


@dataclass
class GameFilters:
    q: str | None = None
    source: str | None = None
    result: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_games(
    db: Session, owner_id: uuid.UUID, filters: GameFilters, page: int, page_size: int
) -> tuple[list[Game], int]:
    where = [Game.owner_id == owner_id]
    if filters.q:
        like = f"%{_escape_like(filters.q.strip())}%"
        where.append(or_(Game.white.ilike(like, escape="\\"), Game.black.ilike(like, escape="\\")))
    if filters.source:
        where.append(Game.source == filters.source)
    if filters.result:
        where.append(Game.result == filters.result)
    if filters.date_from:
        where.append(Game.played_at >= filters.date_from)
    if filters.date_to:
        where.append(Game.played_at <= filters.date_to)

    total = db.scalar(select(func.count()).select_from(Game).where(*where)) or 0
    stmt = (
        select(Game)
        .where(*where)
        .order_by(Game.played_at.desc().nulls_last(), Game.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt)), total


def latest_jobs(db: Session, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, AnalysisJob]:
    if not game_ids:
        return {}
    stmt = (
        select(AnalysisJob)
        .where(AnalysisJob.game_id.in_(game_ids))
        .distinct(AnalysisJob.game_id)
        .order_by(AnalysisJob.game_id, AnalysisJob.created_at.desc())
    )
    return {j.game_id: j for j in db.scalars(stmt)}


def analysis_status(game: Game, job: AnalysisJob | None) -> str:
    if job is not None and job.status in ("queued", "running"):
        return job.status
    if game.current_analysis_id is not None:
        return "completed"
    if job is not None and job.status == "failed":
        return "failed"
    return "none"


def to_game_out(db: Session, games: list[Game]) -> list[GameOut]:
    jobs = latest_jobs(db, [g.id for g in games])
    plain = set(GameOut.model_fields) - {"analysis_status", "has_analysis"}
    return [
        GameOut(
            **{f: getattr(g, f) for f in plain},
            analysis_status=analysis_status(g, jobs.get(g.id)),
            has_analysis=g.current_analysis_id is not None,
        )
        for g in games
    ]


def get_owned_game(db: Session, owner_id: uuid.UUID, game_id: uuid.UUID) -> Game | None:
    """Ownership is part of the query, so another user's id behaves like a missing one."""
    return db.scalar(select(Game).where(Game.id == game_id, Game.owner_id == owner_id))


def delete_game(db: Session, game: Game) -> None:
    db.delete(game)
    db.commit()


def replay_moves(game: Game) -> tuple[str, list[dict]]:
    """Start FEN and per-ply {ply, san, uci, fen} for the stored mainline."""
    parsed = chess.pgn.read_game(io.StringIO(game.pgn))
    if parsed is None:
        return chess.STARTING_FEN, []
    board = parsed.board()
    start_fen = board.fen()
    moves = []
    for ply, move in enumerate(parsed.mainline_moves(), start=1):
        san = board.san(move)
        board.push(move)
        moves.append({"ply": ply, "san": san, "uci": move.uci(), "fen": board.fen()})
    return start_fen, moves
