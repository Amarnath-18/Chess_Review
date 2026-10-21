"""Stockfish access through python-chess (UCI)."""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from functools import lru_cache

import chess
import chess.engine

from app.config import Settings, get_settings
from app.services.classification.classify import Line, PositionEval
from app.services.classification.score import Score


@dataclass(frozen=True)
class SearchLimit:
    """Search bound for one position. At least one of depth / nodes is required."""

    depth: int | None = None
    nodes: int | None = None
    max_seconds: float | None = 30.0  # safety cap per position

    def validate(self, settings: Settings | None = None) -> SearchLimit:
        s = settings or get_settings()
        if self.depth is None and self.nodes is None:
            raise ValueError("a depth or node limit is required")
        if self.depth is not None and not 1 <= self.depth <= s.max_depth:
            raise ValueError(f"depth must be between 1 and {s.max_depth}")
        if self.nodes is not None and not 1 <= self.nodes <= s.max_nodes:
            raise ValueError(f"nodes must be between 1 and {s.max_nodes}")
        return self

    def to_uci_limit(self) -> chess.engine.Limit:
        return chess.engine.Limit(depth=self.depth, nodes=self.nodes, time=self.max_seconds)

    def describe(self) -> dict:
        return {"depth": self.depth, "nodes": self.nodes, "max_seconds": self.max_seconds}


@lru_cache
def get_engine_name() -> str:
    """UCI `id name` of the installed engine (e.g. "Stockfish 17.1"); cached per process."""
    engine = chess.engine.SimpleEngine.popen_uci(get_settings().stockfish_path, timeout=15)
    try:
        return engine.id.get("name", "Stockfish")
    finally:
        engine.quit()


class StockfishEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._engine = chess.engine.SimpleEngine.popen_uci(s.stockfish_path)
        self._engine.configure({"Threads": s.engine_threads, "Hash": s.engine_hash_mb})
        self.name: str = self._engine.id.get("name", "Stockfish")

    def kill(self) -> None:
        """Hard-kill the engine process from another thread (watchdog). Any search in
        progress then raises EngineTerminatedError."""
        try:
            os.kill(self._engine.transport.get_pid(), signal.SIGKILL)
        except (ProcessLookupError, AttributeError, OSError):
            pass

    def __enter__(self) -> StockfishEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._engine.quit()
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError):
            self._engine.close()

    def evaluate(self, board: chess.Board, limit: SearchLimit, multipv: int = 2) -> PositionEval:
        """Evaluate a position. Terminal positions are scored without searching."""
        fen = board.fen()
        outcome = board.outcome()
        if outcome is not None:
            return PositionEval(fen=fen, score=Score.from_outcome(outcome))

        infos = self._engine.analyse(board, limit.to_uci_limit(), multipv=multipv)
        lines: list[Line] = []
        for info in infos:
            pov = info.get("score")
            if pov is None:
                continue
            pv = tuple(m.uci() for m in info.get("pv", ()))
            lines.append(Line(score=Score.from_pov(pov), pv=pv))
        if not lines:
            return PositionEval(fen=fen, score=None)
        depth = infos[0].get("depth")
        return PositionEval(fen=fen, score=lines[0].score, lines=tuple(lines), depth=depth)
