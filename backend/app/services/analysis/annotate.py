"""Annotated PGN: the stored game with the engine's evaluations and move marks embedded in the
formats other chess tools read (`[%eval ...]` comments and NAG symbols)."""
from __future__ import annotations

import io

import chess
import chess.engine
import chess.pgn
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisPosition, AnalysisRun
from app.models.game import Game
from app.services.analysis.store import to_san
from app.services.game_meta import move_notes_for
from app.services.classification.score import Score

# Standard numeric annotation glyphs: $1 ! · $2 ? · $3 !! · $4 ?? · $6 ?!
NAGS = {
    "brilliant": chess.pgn.NAG_BRILLIANT_MOVE,
    "great": chess.pgn.NAG_GOOD_MOVE,
    "inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE,
    "mistake": chess.pgn.NAG_MISTAKE,
    "blunder": chess.pgn.NAG_BLUNDER,
}


def _pov(cp: int | None, mate: int | None) -> chess.engine.PovScore | None:
    if mate is not None:
        return chess.engine.PovScore(chess.engine.Mate(mate), chess.WHITE)
    if cp is not None:
        return chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)
    return None


def _display(cp: int | None, mate: int | None) -> str | None:
    if mate is not None:
        return Score(mate=mate).display()
    if cp is not None:
        return Score(cp=cp).display()
    return None


def _comment_safe(text: str) -> str:
    """A PGN comment ends at the first closing brace, so braces are swapped for brackets and
    line breaks flattened; nothing the owner typed can break out of the comment."""
    return " ".join(text.replace("{", "[").replace("}", "]").split())


def annotate_pgn(
    pgn: str,
    rows: list[AnalysisPosition],
    engine_name: str,
    depth: int | None,
    game_note: str | None = None,
    move_notes: dict[int, str] | None = None,
) -> str:
    """`rows` are one analysis run's positions, ply 0..n. Moves without a saved row are left plain.
    The owner's notes, if given, become PGN comments (braces and line breaks are made safe)."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return pgn.strip() + "\n"
    by_ply = {r.ply: r for r in rows}
    game.headers["Annotator"] = (
        f"Chess Review Lab ({engine_name}" + (f", depth {depth}" if depth else "") + ")"
    )
    start = by_ply.get(0)
    if start is not None:
        pov = _pov(start.score_cp, start.score_mate)
        if pov is not None:
            game.set_eval(pov)
    if game_note:
        game.comment = f"{game.comment} {_comment_safe(game_note)}".strip()

    for ply, node in enumerate(game.mainline(), start=1):
        if move_notes and ply in move_notes:
            node.comment = f"{node.comment} {_comment_safe(move_notes[ply])}".strip()
        row = by_ply.get(ply)
        if row is None:
            continue
        pov = _pov(row.score_cp, row.score_mate)
        if pov is not None:  # checkmate positions have no score; the result says it all
            node.set_eval(pov)
        nag = NAGS.get(row.classification or "")
        if nag is not None:
            node.nags.add(nag)
        if row.classification in ("inaccuracy", "mistake", "blunder"):
            before = by_ply.get(ply - 1)
            best = before.pv_uci[0] if before is not None and before.pv_uci else None
            if best and best != row.played_move_uci:
                best_eval = _display(before.score_cp, before.score_mate)
                note = f"Best was {to_san(before.fen, best)}" + (f" ({best_eval})." if best_eval else ".")
                node.comment = f"{node.comment} {note}".strip()

    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter).strip() + "\n"


def annotated_pgn_for(db: Session, game: Game) -> str | None:
    """The game's PGN with its current review embedded, or None if it has not been analyzed."""
    if game.current_analysis_id is None:
        return None
    run = db.get(AnalysisRun, game.current_analysis_id)
    if run is None or run.status != "completed":
        return None
    rows = list(
        db.scalars(
            select(AnalysisPosition)
            .where(AnalysisPosition.run_id == run.id)
            .order_by(AnalysisPosition.ply)
        )
    )
    return annotate_pgn(
        game.pgn,
        rows,
        run.engine_name,
        run.limit_depth,
        game_note=game.note,
        move_notes=move_notes_for(db, game.id),
    )
