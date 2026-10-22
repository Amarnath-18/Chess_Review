from __future__ import annotations

import io
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import chess
import chess.pgn
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisJob
from app.models.game import Game, GameTag
from app.schemas.games import GameOut
from app.services.game_meta import tags_for


@dataclass
class GameFilters:
    q: str | None = None
    source: str | None = None
    result: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    analyzed: bool | None = None  # True = has a saved review, False = does not
    sort: str = "played"  # "played" (newest game first) or "added" (most recently imported first)
    favorite: bool | None = None  # True = only favourites
    tag: str | None = None  # games carrying this tag


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions(owner_id: uuid.UUID, filters: GameFilters) -> list:
    """The owner is always part of the query; the filters only narrow it further."""
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
    if filters.analyzed is True:
        where.append(Game.current_analysis_id.is_not(None))
    elif filters.analyzed is False:
        where.append(Game.current_analysis_id.is_(None))
    if filters.favorite is True:
        where.append(Game.favorite.is_(True))
    if filters.tag:
        tag = filters.tag.strip().lower()
        where.append(Game.id.in_(select(GameTag.game_id).where(GameTag.tag == tag)))
    return where


def _order(filters: GameFilters) -> tuple:
    if filters.sort == "added":
        return (Game.created_at.desc(), Game.id)
    return (Game.played_at.desc().nulls_last(), Game.created_at.desc(), Game.id)


def count_games(db: Session, owner_id: uuid.UUID, filters: GameFilters) -> int:
    where = _conditions(owner_id, filters)
    return db.scalar(select(func.count()).select_from(Game).where(*where)) or 0


def list_games(
    db: Session, owner_id: uuid.UUID, filters: GameFilters, page: int, page_size: int
) -> tuple[list[Game], int]:
    total = count_games(db, owner_id, filters)
    stmt = (
        select(Game)
        .where(*_conditions(owner_id, filters))
        .order_by(*_order(filters))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt)), total


def iter_pgn(
    db: Session,
    owner_id: uuid.UUID,
    filters: GameFilters,
    batch: int = 200,
    annotated: bool = False,
) -> Iterator[str]:
    """The stored PGN of every matching game, in list order, read in batches.

    With `annotated`, analyzed games carry their evaluations and move marks; the rest stay plain.
    """
    from app.services.analysis.annotate import annotated_pgn_for  # avoids an import cycle

    offset = 0
    while True:
        games = db.scalars(
            select(Game)
            .where(*_conditions(owner_id, filters))
            .order_by(*_order(filters))
            .offset(offset)
            .limit(batch)
        ).all()
        if not games:
            return
        for game in games:
            text = annotated_pgn_for(db, game) if annotated else None
            yield (text or game.pgn).strip() + "\n\n"
        offset += batch


def safe_filename(stem: str, ext: str = "pgn") -> str:
    """ASCII-only file name, so a player name can never inject header characters."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")[:80] or "game"
    return f"{clean}.{ext}"


def game_filename(game: Game) -> str:
    stamp = game.played_at.isoformat() if game.played_at else "undated"
    return safe_filename(f"{game.white}-vs-{game.black}-{stamp}")


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
    tags = tags_for(db, [g.id for g in games])
    plain = set(GameOut.model_fields) - {"analysis_status", "has_analysis", "tags", "has_note"}
    return [
        GameOut(
            **{f: getattr(g, f) for f in plain},
            analysis_status=analysis_status(g, jobs.get(g.id)),
            has_analysis=g.current_analysis_id is not None,
            tags=tags[g.id],
            has_note=bool(g.note),
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
