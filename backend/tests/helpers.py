"""Test doubles for the analysis engine."""
from __future__ import annotations

import chess
import chess.engine

from app.services.analysis.engine import SearchLimit
from app.services.classification.classify import Line, PositionEval
from app.services.classification.score import Score


class FakeEngine:
    """Deterministic stand-in for Stockfish.

    fail_at:     1-based evaluate() call number that raises `error`
    unavailable: 1-based call numbers that return an unavailable (None) score
    on_call:     hook(call_number) executed at the start of every evaluate()
    """

    name = "FakeFish 1.0"

    def __init__(self, fail_at=None, error=None, unavailable=(), on_call=None):
        self.fail_at = fail_at
        self.error = error or RuntimeError("boom")
        self.unavailable = set(unavailable)
        self.on_call = on_call
        self.calls = 0
        self.killed = False
        self.closed = 0

    def evaluate(self, board: chess.Board, limit: SearchLimit, multipv: int = 2) -> PositionEval:
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls)
        if self.fail_at == self.calls:
            raise self.error
        fen = board.fen()
        outcome = board.outcome()
        if outcome is not None:
            return PositionEval(fen=fen, score=Score.from_outcome(outcome))
        if self.calls in self.unavailable:
            return PositionEval(fen=fen, score=None)
        legal = [m.uci() for m in board.legal_moves]
        # One line per requested rank (as many as there are legal moves), best first.
        lines = [
            Line(Score(cp=30 if i == 0 else -200 - 20 * (i - 1)), (legal[i],))
            for i in range(min(multipv, len(legal)))
        ]
        return PositionEval(fen=fen, score=lines[0].score, lines=tuple(lines), depth=limit.depth)

    def kill(self) -> None:
        self.killed = True

    def close(self) -> None:
        self.closed += 1


TERMINATED = chess.engine.EngineTerminatedError("engine died")


def seed_review(db_factory, game_id, specs: dict[int, dict] | None = None):
    """Save a finished review for a game without running an engine, for tests that need exact
    evaluations. `specs[ply]` may set cp, mate, lines [(cp, [uci, ...]), ...], cls, loss and
    missed_win for that position; everything else is a quiet, equal position."""
    import io
    import uuid

    import chess.pgn

    from app.models.analysis import AnalysisPosition, AnalysisRun
    from app.models.game import Game

    specs = specs or {}
    with db_factory() as db:
        game = db.get(Game, uuid.UUID(str(game_id)))
        pgn = chess.pgn.read_game(io.StringIO(game.pgn))
        board = pgn.board()
        run = AnalysisRun(
            game_id=game.id,
            status="completed",
            engine_name="Seeded 1.0",
            limit_depth=10,
            multipv=3,
            class_config={},
            class_config_hash="seed",
            cache_key=f"seed-{uuid.uuid4()}",
            summary={},
        )
        db.add(run)
        db.flush()
        moves = list(pgn.mainline_moves())
        for ply in range(len(moves) + 1):
            s = specs.get(ply, {})
            lines = s.get("lines", [(s.get("cp", 0), [])])
            db.add(
                AnalysisPosition(
                    run_id=run.id,
                    ply=ply,
                    fen=board.fen(),
                    score_cp=s.get("cp", 0) if s.get("mate") is None else None,
                    score_mate=s.get("mate"),
                    lines=[
                        {"cp": cp, "mate": None, "pv": pv} for cp, pv in lines
                    ],
                    pv_uci=lines[0][1],
                    played_move_uci=moves[ply - 1].uci() if ply else None,
                    played_move_san=None,
                    classification=s.get("cls", "best") if ply else None,
                    loss_pct=s.get("loss", 0.0) if ply else None,
                    missed_win=s.get("missed_win", False),
                    depth_reached=10,
                )
            )
            if ply < len(moves):
                board.push(moves[ply])
        game.current_analysis_id = run.id
        db.commit()
        return run.id
