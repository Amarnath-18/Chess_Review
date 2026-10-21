from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import chess
import chess.pgn

from app.config import get_settings
from app.services.analysis.engine import SearchLimit, StockfishEngine
from app.services.classification.classify import MoveResult, PositionEval, classify_game
from app.services.classification.config import ClassificationConfig
from app.services.classification.summary import summarize


@dataclass
class GameAnalysis:
    positions: list[PositionEval]  # len(moves) + 1
    moves_uci: list[str]
    moves_san: list[str]
    results: list[MoveResult | None]
    summary: dict
    engine_name: str
    limit: SearchLimit
    multipv: int
    config_hash: str


def replay(game: chess.pgn.Game) -> tuple[chess.Board, list[chess.Move], list[str]]:
    """Replay the mainline from its starting position; returns start board, moves, SANs."""
    start = game.board()
    moves = list(game.mainline_moves())
    max_plies = get_settings().max_plies
    if len(moves) > max_plies:
        raise ValueError(f"game has {len(moves)} plies; the limit is {max_plies}")
    board = start.copy()
    sans = []
    for m in moves:
        sans.append(board.san(m))
        board.push(m)
    return start, moves, sans


class Evaluator(Protocol):
    name: str

    def evaluate(
        self, board: chess.Board, limit: SearchLimit, multipv: int = 2
    ) -> PositionEval: ...


def evaluate_game(
    game: chess.pgn.Game,
    engine: Evaluator,
    limit: SearchLimit,
    multipv: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
    on_position: Callable[[int, PositionEval, int], None] | None = None,
) -> tuple[list[PositionEval], list[str], list[str]]:
    """Search every position of the game once (N moves -> N+1 searches).

    on_position(ply, position, total) fires after each search (ply 0 = start position);
    exceptions it raises abort the analysis.
    """
    limit.validate()
    start, moves, sans = replay(game)
    board = start.copy()
    total = len(moves) + 1
    positions: list[PositionEval] = []

    def record(ply: int) -> None:
        pos = engine.evaluate(board, limit, multipv)
        positions.append(pos)
        if on_position:
            on_position(ply, pos, total)
        if on_progress:
            on_progress(ply + 1, total)

    record(0)
    for i, move in enumerate(moves):
        board.push(move)
        record(i + 1)
    return positions, [m.uci() for m in moves], sans


def analyze_game(
    game: chess.pgn.Game,
    engine: StockfishEngine,
    limit: SearchLimit,
    config: ClassificationConfig | None = None,
    multipv: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
) -> GameAnalysis:
    config = config or ClassificationConfig()
    positions, moves_uci, moves_san = evaluate_game(game, engine, limit, multipv, on_progress)
    results = classify_game(positions, moves_uci, config)
    summary = summarize(positions, results, config, complete=True)
    return GameAnalysis(
        positions=positions,
        moves_uci=moves_uci,
        moves_san=moves_san,
        results=results,
        summary=summary,
        engine_name=engine.name,
        limit=limit,
        multipv=multipv,
        config_hash=config.config_hash(),
    )
