"""Persistence helpers for analysis runs and positions."""
from __future__ import annotations

import hashlib
import uuid

import chess
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisPosition, AnalysisRun
from app.models.base import utcnow
from app.services.analysis.engine import SearchLimit
from app.services.classification.classify import Line, MoveResult, PositionEval
from app.services.classification.score import Score, win_pct_white


def make_cache_key(
    engine_name: str, limit: SearchLimit, multipv: int, config_hash: str
) -> str:
    """Two analyses are interchangeable iff engine, search limits, multipv and the
    classification settings all match."""
    raw = f"{engine_name}|d={limit.depth}|n={limit.nodes}|pv={multipv}|cfg={config_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


def find_completed_run(db: Session, game_id: uuid.UUID, cache_key: str) -> AnalysisRun | None:
    return db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.game_id == game_id,
            AnalysisRun.cache_key == cache_key,
            AnalysisRun.status == "completed",
        )
    )


def _score_cols(score: Score | None, prefix: str = "score") -> dict:
    cols: dict = {f"{prefix}_cp": None, f"{prefix}_mate": None}
    if prefix == "score":
        cols["terminal_result"] = None
    if score is None:
        return cols
    cols[f"{prefix}_cp"] = score.cp
    cols[f"{prefix}_mate"] = score.mate
    if prefix == "score":
        cols["terminal_result"] = score.final
    return cols


def position_row(
    run_id: uuid.UUID,
    ply: int,
    pos: PositionEval,
    played_uci: str | None,
    played_san: str | None,
) -> AnalysisPosition:
    top, alt = pos.top, pos.alt
    return AnalysisPosition(
        run_id=run_id,
        ply=ply,
        fen=pos.fen,
        **_score_cols(pos.score),
        win_pct=win_pct_white(pos.score) if pos.score is not None else None,
        depth_reached=pos.depth,
        pv_uci=list(top.pv) if top is not None else None,
        lines=[{"cp": ln.score.cp, "mate": ln.score.mate, "pv": list(ln.pv)} for ln in pos.lines]
        or None,
        **_score_cols(alt.score if alt else None, prefix="alt_score"),
        alt_pv_uci=list(alt.pv) if alt is not None else None,
        played_move_uci=played_uci,
        played_move_san=played_san,
    )


def _score_from(cp: int | None, mate: int | None, final: str | None = None) -> Score | None:
    if cp is None and mate is None and final is None:
        return None
    return Score(cp=cp, mate=mate, final=final)


def row_to_position(row: AnalysisPosition) -> PositionEval:
    """Rebuild the pure-domain object so stored evaluations can be re-classified."""
    score = _score_from(row.score_cp, row.score_mate, row.terminal_result)
    lines: list[Line] = []
    if row.lines:
        for item in row.lines:
            s = _score_from(item.get("cp"), item.get("mate"))
            if s is not None:
                lines.append(Line(s, tuple(item.get("pv") or ())))
    elif row.pv_uci is not None and score is not None and row.terminal_result is None:
        lines.append(Line(score, tuple(row.pv_uci)))
        alt = _score_from(row.alt_score_cp, row.alt_score_mate)
        if alt is not None:
            lines.append(Line(alt, tuple(row.alt_pv_uci or ())))
    return PositionEval(fen=row.fen, score=score, lines=tuple(lines), depth=row.depth_reached)


def write_classifications(
    db: Session, run_id: uuid.UUID, results: list[MoveResult | None]
) -> None:
    """results[i] classifies the move that produced ply i+1."""
    rows = [
        {
            "run_id": run_id,
            "ply": i + 1,
            "classification": r.classification.value if r else None,
            "loss_pct": r.loss if r else None,
            "missed_win": bool(r and r.missed_win),
            "is_sacrifice": bool(r and r.is_sacrifice),
        }
        for i, r in enumerate(results)
    ]
    if rows:
        db.execute(update(AnalysisPosition), rows)


def fail_run(db: Session, run_id: uuid.UUID, error: str) -> None:
    """Mark a run failed and drop its partial positions (never exposed as a review)."""
    db.execute(delete(AnalysisPosition).where(AnalysisPosition.run_id == run_id))
    db.execute(
        update(AnalysisRun)
        .where(AnalysisRun.id == run_id, AnalysisRun.status == "running")
        .values(status="failed", error=error[:2000], finished_at=utcnow())
    )


def board_for(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def to_san(fen: str, uci: str | None) -> str | None:
    if not uci:
        return None
    board = board_for(fen)
    if board is None:
        return None
    try:
        return board.san(chess.Move.from_uci(uci))
    except ValueError:
        return None


def pv_to_san(fen: str, pv: list[str] | None, limit: int = 8) -> list[str]:
    board = board_for(fen)
    out: list[str] = []
    if board is None or not pv:
        return out
    for uci in pv[:limit]:
        try:
            move = chess.Move.from_uci(uci)
            out.append(board.san(move))
            board.push(move)
        except ValueError:
            break
    return out
