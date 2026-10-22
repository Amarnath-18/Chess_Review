import io

import chess
import chess.pgn

from app.models.analysis import AnalysisPosition
from app.services.analysis.annotate import annotate_pgn

PGN = """[White "A"]
[Black "B"]
[Result "0-1"]

1. f3 {[%clk 0:03:00]} e5 {[%clk 0:02:59]} 2. g4 {[%clk 0:02:50]} Qh4# {[%clk 0:02:40]} 0-1
"""


def row(ply, fen, cp=None, mate=None, pv=None, played=None, cls=None):
    return AnalysisPosition(
        ply=ply, fen=fen, score_cp=cp, score_mate=mate, pv_uci=pv, played_move_uci=played, classification=cls
    )


def rows():
    board = chess.Board()
    out = [row(0, board.fen(), cp=30, pv=["e2e4"])]
    steps = [
        ("f2f3", dict(cp=-20, pv=["e7e5"], cls="inaccuracy")),
        ("e7e5", dict(cp=-10, pv=["e2e4"], cls="best")),
        ("g2g4", dict(mate=-1, pv=["d8h4"], cls="blunder")),
        ("d8h4", dict(cls="best")),  # checkmate: no score
    ]
    for uci, fields in steps:
        board.push_uci(uci)
        out.append(row(len(out), board.fen(), played=uci, **fields))
    return out


def test_marks_evals_and_best_move_are_embedded_and_clocks_survive():
    text = annotate_pgn(PGN, rows(), "Stockfish 17.1", 16)
    game = chess.pgn.read_game(io.StringIO(text))
    assert not game.errors
    assert game.headers["Annotator"] == "Chess Review Lab (Stockfish 17.1, depth 16)"
    n1, n2, n3, n4 = list(game.mainline())

    assert chess.pgn.NAG_DUBIOUS_MOVE in n1.nags and "Best was e4 (+0.30)." in n1.comment
    assert chess.pgn.NAG_BLUNDER in n3.nags and "Best was" in n3.comment
    assert not n2.nags  # good moves carry no symbol
    assert n3.eval().white().mate() == -1  # [%eval #-1]
    assert n4.eval() is None  # checkmate has no engine score; the result says it
    assert n1.clock() == 180 and n4.clock() == 160  # existing clock comments are kept


def test_game_with_no_saved_rows_is_returned_unannotated_but_valid():
    text = annotate_pgn(PGN, [], "Stockfish", None)
    game = chess.pgn.read_game(io.StringIO(text))
    assert not game.errors and [n.san() for n in game.mainline()] == ["f3", "e5", "g4", "Qh4#"]
