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
