"""Pure move classification from normalized evaluations (no engine needed)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import chess

from app.services.classification.config import ClassificationConfig
from app.services.classification.score import Score, favours, win_pct_for

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


class MoveClass(StrEnum):
    BRILLIANT = "brilliant"
    GREAT = "great"
    BEST = "best"
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"


ERROR_CLASSES = (MoveClass.INACCURACY, MoveClass.MISTAKE, MoveClass.BLUNDER)


@dataclass(frozen=True)
class Line:
    """One engine line from a position. `score` is White's perspective."""

    score: Score
    pv: tuple[str, ...] = ()  # UCI moves

    @property
    def move(self) -> str | None:
        return self.pv[0] if self.pv else None


@dataclass(frozen=True)
class PositionEval:
    fen: str
    score: Score | None  # None = unavailable (never "0")
    lines: tuple[Line, ...] = ()  # best first; empty for terminal/unavailable
    depth: int | None = None

    @property
    def top(self) -> Line | None:
        return self.lines[0] if self.lines else None

    @property
    def alt(self) -> Line | None:
        return self.lines[1] if len(self.lines) > 1 else None


@dataclass(frozen=True)
class MoveResult:
    classification: MoveClass
    loss: float  # win% points lost, mover's perspective, >= 0
    missed_win: bool = False
    is_sacrifice: bool = False


def material_balance(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for piece in board.piece_map().values():
        v = PIECE_VALUES[piece.piece_type]
        total += v if piece.color == color else -v
    return total


def is_sacrifice(
    board_before: chess.Board,
    played_uci: str,
    follow_up_pv: tuple[str, ...],
    config: ClassificationConfig,
) -> bool:
    """True if the mover gives up material that is not recovered along the PV.

    `follow_up_pv` is the engine's best line from the position AFTER the played move
    (opponent's reply first).
    """
    mover = board_before.turn
    start = material_balance(board_before, mover)
    board = board_before.copy(stack=False)
    board.push(chess.Move.from_uci(played_uci))
    balances: list[int] = []
    # opponent reply + `sac_horizon` further plies
    for uci in follow_up_pv[: 1 + config.sac_horizon]:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            break
        board.push(move)
        balances.append(material_balance(board, mover))
    if not balances:
        return False
    threshold = start - config.sac_min_material
    return all(b <= threshold for b in balances)


def classify_move(
    before: PositionEval,
    after: PositionEval,
    played_uci: str,
    config: ClassificationConfig,
) -> MoveResult | None:
    """Classify one move. Returns None if either evaluation is unavailable."""
    if before.score is None or after.score is None:
        return None

    board_before = chess.Board(before.fen)
    mover = board_before.turn
    wb = win_pct_for(before.score, mover)
    wa = win_pct_for(after.score, mover)

    top = before.top
    played_is_top = top is not None and top.move == played_uci
    loss = 0.0 if played_is_top else max(0.0, wb - wa)

    missed_win = False
    if not played_is_top:
        had_win = wb >= config.missed_win_before or favours(before.score, mover)
        kept_win = wa >= config.missed_win_after or favours(after.score, mover)
        missed_win = had_win and not kept_win

    if loss >= config.blunder_loss:
        return MoveResult(MoveClass.BLUNDER, loss, missed_win)
    if loss >= config.mistake_loss:
        return MoveResult(MoveClass.MISTAKE, loss, missed_win)
    if loss >= config.inaccuracy_loss:
        return MoveResult(MoveClass.INACCURACY, loss, missed_win)
    if loss >= config.excellent_loss:
        return MoveResult(MoveClass.GOOD, loss, missed_win)

    # From here the move is best or nearly best, so it may earn Brilliant / Great.
    base = MoveClass.BEST if (played_is_top or loss < config.best_loss) else MoveClass.EXCELLENT

    if _is_brilliant(board_before, before, after, played_uci, played_is_top, wa, loss, config):
        return MoveResult(MoveClass.BRILLIANT, loss, is_sacrifice=True)
    if base is MoveClass.BEST and _is_great(before, played_is_top, wb, mover, config):
        return MoveResult(MoveClass.GREAT, loss)
    return MoveResult(base, loss)


def _is_great(
    before: PositionEval,
    played_is_top: bool,
    wb: float,
    mover: chess.Color,
    config: ClassificationConfig,
) -> bool:
    if not played_is_top or before.top is None or before.alt is None:
        return False  # forced / single legal move, or not a clear top move
    gap = win_pct_for(before.top.score, mover) - win_pct_for(before.alt.score, mover)
    if gap < config.great_gap:
        return False
    mate = before.top.score.mate
    # Finding the only move in a long mating sequence counts; delivering a short mate does not.
    mate_involved = mate is not None and abs(mate) > config.trivial_mate_max
    undecided = config.great_window_low < wb < config.great_window_high
    return undecided or mate_involved


def _is_brilliant(
    board_before: chess.Board,
    before: PositionEval,
    after: PositionEval,
    played_uci: str,
    played_is_top: bool,
    wa: float,
    loss: float,
    config: ClassificationConfig,
) -> bool:
    """Best or nearly-best move that is a genuine piece sacrifice (see ClassificationConfig)."""
    mover = board_before.turn
    if loss > config.brilliant_max_loss or wa < config.brilliant_min_after:
        return False  # not best/nearly best, or it leaves the mover in a bad position
    # "Not completely winning even if you hadn't found the move": judge the best line that
    # does not start with the played move.
    if played_is_top:
        reference = before.alt or before.top
    else:
        reference = before.top
    if reference is None:
        return False
    if win_pct_for(reference.score, mover) >= config.brilliant_max_without:
        return False
    after_top = after.top
    if after_top is None:
        return False
    mate = after_top.score.mate
    if mate is not None and abs(mate) <= config.brilliant_trivial_mate:
        return False
    return is_sacrifice(board_before, played_uci, after_top.pv, config)


def classify_game(
    positions: list[PositionEval],
    moves_uci: list[str],
    config: ClassificationConfig,
) -> list[MoveResult | None]:
    """positions has len(moves)+1 entries; result[i] classifies moves_uci[i]."""
    if len(positions) != len(moves_uci) + 1:
        raise ValueError("need one more position than moves")
    return [
        classify_move(positions[i], positions[i + 1], uci, config)
        for i, uci in enumerate(moves_uci)
    ]
