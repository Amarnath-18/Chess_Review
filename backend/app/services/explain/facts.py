"""Deterministic facts about one move, built from what the engine saved plus python-chess.

The language model is never asked "what is going on in this position?" from a bare FEN. It is
given these facts and a list of the moves it may mention; everything it says is checked against
them (see validate.py). No network, no model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

from app.services.classification.classify import PIECE_VALUES, PositionEval
from app.services.classification.score import Score, win_pct_for
from app.services.stats import phase_of

PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}
MOTIFS = (
    "fork",
    "hanging piece",
    "missed capture",
    "missed mate",
    "allows mate",
    "missed check",
)
PV_PLIES = 6
MAX_LINES = 3


@dataclass
class Facts:
    data: dict  # what the model sees
    allowed_moves: set[str] = field(default_factory=set)  # SAN the explanation may mention
    allowed_squares: set[str] = field(default_factory=set)  # squares it may name on their own
    evals: list[float] = field(default_factory=list)  # pawn evaluations it may quote
    mates: set[int] = field(default_factory=set)  # mate distances it may quote


def norm_san(san: str) -> str:
    """Compare moves ignoring check marks and annotation symbols."""
    return san.rstrip("+#!?")


def eval_text(score: Score | None, color: chess.Color) -> str | None:
    """Evaluation from the mover's point of view: +1.2 means the mover is better."""
    if score is None:
        return None
    if score.final is not None:
        return score.final
    if score.mate is not None:
        n = score.mate if color == chess.WHITE else -score.mate
        return f"mate in {n} for you" if n > 0 else f"you are mated in {-n}"
    cp = score.cp if color == chess.WHITE else -(score.cp or 0)
    return f"{(cp or 0) / 100:+.1f}"


def _pawns(score: Score | None, color: chess.Color) -> float | None:
    if score is None or score.cp is None:
        return None
    return (score.cp if color == chess.WHITE else -score.cp) / 100


def _mate_for(score: Score | None, color: chess.Color) -> int | None:
    """Mate distance, positive when `color` mates, negative when `color` is mated."""
    if score is None or score.mate is None:
        return None
    return score.mate if color == chess.WHITE else -score.mate


def pv_san(board: chess.Board, ucis: list[str], limit: int = PV_PLIES) -> list[str]:
    b = board.copy(stack=False)
    out: list[str] = []
    for uci in ucis[:limit]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in b.legal_moves:
            break
        out.append(b.san(move))
        b.push(move)
    return out


def _material(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for piece in board.piece_map().values():
        total += PIECE_VALUES[piece.piece_type] * (1 if piece.color == color else -1)
    return total


def _hanging(board: chess.Board, color: chess.Color) -> set[tuple[int, int]]:
    """(piece type, square) of `color`'s knights, bishops, rooks and queens the opponent could
    win: attacked and either undefended or attacked by a cheaper piece."""
    out: set[tuple[int, int]] = set()
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type in (chess.PAWN, chess.KING):
            continue
        attackers = board.attackers(not color, sq)
        if not attackers:
            continue
        cheapest = min(PIECE_VALUES[board.piece_type_at(a)] for a in attackers)
        if not board.attackers(color, sq) or cheapest < PIECE_VALUES[piece.piece_type]:
            out.add((piece.piece_type, sq))
    return out


def _is_fork(board_after: chess.Board, move: chess.Move) -> bool:
    """The moved piece (not a pawn or king) attacks two or more enemy pieces worth capturing."""
    piece = board_after.piece_at(move.to_square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return False
    me = piece.color
    targets = 0
    for sq in board_after.attacks(move.to_square):
        victim = board_after.piece_at(sq)
        if victim is None or victim.color == me or victim.piece_type == chess.PAWN:
            continue
        undefended = not board_after.attackers(not me, sq)
        bigger = PIECE_VALUES[victim.piece_type] > PIECE_VALUES[piece.piece_type]
        if victim.piece_type == chess.KING or undefended or bigger:
            targets += 1
    return targets >= 2


def _describe(board: chess.Board, move: chess.Move) -> dict:
    san = board.san(move)
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        captured = chess.Piece(chess.PAWN, not board.turn)
    return {
        "san": san,
        "uci": move.uci(),
        "captures": PIECE_NAMES[captured.piece_type] if captured else None,
        "gives_check": board.gives_check(move),
        "castles": board.is_castling(move),
        "promotes": move.promotion is not None,
    }


def build_facts(
    before: PositionEval,
    after: PositionEval,
    played_uci: str,
    classification: str | None,
    ply: int,
) -> Facts | None:
    """Facts for the move `played_uci` made from `before`. None if the data cannot support them
    (no engine lines, or a move that is not legal in the position)."""
    board = chess.Board(before.fen)
    me = board.turn
    try:
        played = chess.Move.from_uci(played_uci)
    except ValueError:
        return None
    if played not in board.legal_moves or not before.lines or before.score is None or after.score is None:
        return None
    best_uci = before.lines[0].pv[0] if before.lines[0].pv else None
    if best_uci is None:
        return None
    best = chess.Move.from_uci(best_uci)
    if best not in board.legal_moves:
        return None

    played_info = _describe(board, played)
    best_info = _describe(board, best)
    allowed = {played_info["san"], best_info["san"]}
    evals: list[float] = []
    mates: set[int] = set()

    lines_out = []
    for rank, ln in enumerate(before.lines[:MAX_LINES], start=1):
        sans = pv_san(board, list(ln.pv))
        if not sans:
            continue
        allowed.update(sans)
        p, m = _pawns(ln.score, me), _mate_for(ln.score, me)
        if p is not None:
            evals.append(p)
        if m is not None:
            mates.add(abs(m))
        lines_out.append({"rank": rank, "first_move": sans[0], "eval": eval_text(ln.score, me), "line": sans})

    after_board = board.copy(stack=False)
    after_board.push(played)
    reply = None
    reply_move = None
    if after.lines and after.lines[0].pv:
        try:
            cand = chess.Move.from_uci(after.lines[0].pv[0])
        except ValueError:
            cand = None
        if cand is not None and cand in after_board.legal_moves:
            reply_move = cand
            reply = _describe(after_board, cand)
            allowed.add(reply["san"])
            allowed.update(pv_san(after_board, list(after.lines[0].pv)))

    before_hang = _hanging(board, me)
    after_hang = _hanging(after_board, me)
    new_hanging = [
        {"piece": PIECE_NAMES[t], "square": chess.square_name(sq)}
        for t, sq in sorted(after_hang - before_hang, key=lambda x: x[1])
    ]
    material_after_reply = None
    if reply_move is not None:
        b2 = after_board.copy(stack=False)
        b2.push(reply_move)
        material_after_reply = _material(b2, me) - _material(board, me)

    win_before = win_pct_for(before.score, me)
    win_after = win_pct_for(after.score, me)
    mate_before = _mate_for(before.lines[0].score, me)
    mate_after = _mate_for(after.score, me)
    for s in (before.score, after.score):
        p = _pawns(s, me)
        if p is not None:
            evals.append(p)
    for m in (mate_before, mate_after):
        if m is not None:
            mates.add(abs(m))

    missed_capture = (
        best_info["captures"]
        if best_info["captures"] and best_info["captures"] != "pawn" and not played_info["captures"]
        else None
    )
    is_best = played == best
    motifs: list[str] = []
    best_after = board.copy(stack=False)
    best_after.push(best)
    if not is_best and _is_fork(best_after, best):
        motifs.append("fork")
    if not is_best and missed_capture:
        motifs.append("missed capture")
    if not is_best and mate_before is not None and mate_before > 0 and not (mate_after and mate_after > 0):
        motifs.append("missed mate")
    if mate_after is not None and mate_after < 0:
        motifs.append("allows mate")
    if new_hanging:
        motifs.append("hanging piece")
    if (
        not is_best
        and best_info["gives_check"]
        and not played_info["gives_check"]
        and "missed mate" not in motifs
    ):
        motifs.append("missed check")

    squares = {chess.square_name(sq) for sq in board.piece_map()}
    squares |= {chess.square_name(sq) for sq in after_board.piece_map()}
    for mv in (played, best, reply_move):
        if mv is not None:
            squares |= {chess.square_name(mv.from_square), chess.square_name(mv.to_square)}

    data = {
        "side_to_move": "white" if me == chess.WHITE else "black",
        "move_number": board.fullmove_number,
        "phase": phase_of(ply, before.fen),
        "classification": classification,
        "played": played_info,
        "engine_best": best_info,
        "played_is_engine_best": is_best,
        "win_chance_before_percent": round(win_before, 1),
        "win_chance_after_percent": round(win_after, 1),
        "win_chance_lost_points": round(max(0.0, win_before - win_after), 1),
        "eval_before": eval_text(before.score, me),
        "eval_after": eval_text(after.score, me),
        "engine_lines": lines_out,
        "after_the_played_move": {
            "opponents_best_reply": reply,
            "you_get_mated_in": (-mate_after if mate_after is not None and mate_after < 0 else None),
            "pieces_newly_attacked_and_losable": new_hanging,
            "material_change_for_you_after_the_reply": material_after_reply,
        },
        "missed": {
            "you_could_have_mated_in": mate_before if mate_before and mate_before > 0 else None,
            "capture_available": missed_capture,
        },
        "motifs": motifs,
        "allowed_moves": sorted(allowed),
    }
    return Facts(data, allowed, squares, evals, mates)
