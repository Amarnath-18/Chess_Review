"""Needs the real Stockfish binary (present in the backend image)."""
from pathlib import Path

import chess
import chess.pgn
import pytest

from app.services.analysis.engine import SearchLimit, StockfishEngine
from app.services.analysis.runner import analyze_game
from app.services.classification.classify import MoveClass

pytestmark = pytest.mark.engine
FIXTURES = Path(__file__).parent.parent / "fixtures"
LIMIT = SearchLimit(depth=10, max_seconds=20)


@pytest.fixture(scope="module")
def engine():
    with StockfishEngine() as e:
        yield e


def load(name: str) -> chess.pgn.Game:
    with open(FIXTURES / name, encoding="utf-8") as fh:
        game = chess.pgn.read_game(fh)
    assert game is not None
    return game


def test_forced_mate_is_reported_as_mate_from_whites_view(engine):
    # AT-04: back-rank mate in 1 for White.
    pos = engine.evaluate(chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"), LIMIT)
    assert pos.score.mate == 1
    assert pos.top.move == "a1a8"


def test_mate_for_black_is_negative(engine):
    pos = engine.evaluate(chess.Board("r3k3/8/8/8/8/8/5PPP/6K1 b - - 0 1"), LIMIT)
    assert pos.score.mate == -1


def test_checkmated_position_is_scored_without_search(engine):
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    pos = engine.evaluate(board, LIMIT)
    assert pos.score.final == "0-1" and pos.lines == ()


def test_fools_mate_game(engine):
    a = analyze_game(load("fools_mate.pgn"), engine, LIMIT)
    assert len(a.positions) == len(a.moves_uci) + 1 == 5
    assert a.positions[-1].score.final == "0-1"
    # 2.g4?? allows mate in one.
    assert a.results[2].classification is MoveClass.BLUNDER
    # 2...Qh4# is the best move (a short mate is never "great").
    assert a.results[3].classification is MoveClass.BEST
    assert a.summary["complete"] and a.summary["analyzed_moves"] == 4
    assert a.summary["counts"]["white"]["blunder"] >= 1


def test_normal_game_has_a_record_for_every_move(engine):
    a = analyze_game(load("short_game.pgn"), engine, LIMIT)
    assert len(a.results) == len(a.moves_uci) == 19
    assert all(r is not None for r in a.results)
    assert a.summary["complete"]
    # Evaluations always carry exactly one representation.
    for p in a.positions:
        assert p.score is not None


def test_limits_are_enforced():
    with pytest.raises(ValueError):
        SearchLimit(depth=999).validate()
    with pytest.raises(ValueError):
        SearchLimit().validate()
