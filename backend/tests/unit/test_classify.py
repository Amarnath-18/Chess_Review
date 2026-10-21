import chess
import pytest

from app.services.classification.classify import (
    Line,
    MoveClass,
    PositionEval,
    classify_game,
    classify_move,
    is_sacrifice,
)
from app.services.classification.config import ClassificationConfig
from app.services.classification.score import Score
from app.services.classification.summary import summarize

CFG = ClassificationConfig()
START = chess.STARTING_FEN
AFTER_E4_BLACK = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def after_fen(fen: str, uci: str) -> str:
    b = chess.Board(fen)
    b.push_uci(uci)
    return b.fen()


def pe(fen, cp=None, mate=None, pv=(), alt=None, final=None, unavailable=False):
    """Build a PositionEval. `alt` is (cp, pv) for the second-best line."""
    if unavailable:
        return PositionEval(fen=fen, score=None)
    score = Score(cp=cp, mate=mate, final=final)
    lines = ()
    if pv or alt:
        lines = (Line(score, tuple(pv)),)
        if alt:
            lines += (Line(Score(cp=alt[0]), tuple(alt[1])),)
    return PositionEval(fen=fen, score=score, lines=lines)


def move(fen, played, before_kw, after_kw):
    before = pe(fen, **before_kw)
    after = pe(after_fen(fen, played), **after_kw)
    return classify_move(before, after, played, CFG)


# ---- ordinary moves, White -------------------------------------------------


def test_top_move_is_best():
    r = move(START, "e2e4", dict(cp=30, pv=["e2e4"]), dict(cp=30))
    assert r.classification is MoveClass.BEST and r.loss == 0


@pytest.mark.parametrize(
    "after_cp, expected",
    [
        (90, MoveClass.EXCELLENT),  # under 2 points lost
        (60, MoveClass.GOOD),  # ~3.6 points lost (the 2-5 band)
        (0, MoveClass.INACCURACY),  # ~9 win% points
        (-100, MoveClass.MISTAKE),  # ~18
        (-300, MoveClass.BLUNDER),  # ~34
    ],
)
def test_loss_thresholds_white(after_cp, expected):
    r = move(START, "a2a3", dict(cp=100, pv=["d2d4"]), dict(cp=after_cp))
    assert r.classification is expected


def test_search_noise_never_gives_negative_loss():
    r = move(START, "a2a3", dict(cp=100, pv=["d2d4"]), dict(cp=150))
    assert r.loss == 0 and r.classification is MoveClass.BEST


# ---- side-to-move perspective ---------------------------------------------


def test_black_loss_mirrors_white_loss():
    white = move(START, "a2a3", dict(cp=100, pv=["d2d4"]), dict(cp=0))
    # Same situation for Black: evaluations are stored from White's view, so signs flip.
    black = move(AFTER_E4_BLACK, "a7a6", dict(cp=-100, pv=["d7d5"]), dict(cp=0))
    assert black.classification is white.classification is MoveClass.INACCURACY
    assert black.loss == pytest.approx(white.loss)


def test_black_improving_white_eval_is_a_loss_for_black():
    r = move(AFTER_E4_BLACK, "a7a6", dict(cp=0, pv=["e7e5"]), dict(cp=300))
    assert r.classification is MoveClass.BLUNDER


# ---- mates ------------------------------------------------------------------


def test_missed_forced_mate_into_equal_position_is_blunder_and_missed_win():
    r = move(START, "a2a3", dict(mate=2, pv=["d2d4"]), dict(cp=50))
    assert r.classification is MoveClass.BLUNDER and r.missed_win


def test_dropping_from_mate_to_still_winning_is_not_missed_win():
    r = move(START, "a2a3", dict(mate=2, pv=["d2d4"]), dict(cp=600))
    assert not r.missed_win


def test_allowing_mate_against_you_is_blunder():
    r = move(START, "a2a3", dict(cp=0, pv=["d2d4"]), dict(mate=-1))
    assert r.classification is MoveClass.BLUNDER and r.loss == pytest.approx(50.0)


def test_slower_mate_is_not_penalised():
    r = move(START, "a2a3", dict(mate=2, pv=["d2d4"]), dict(mate=3))
    assert r.classification is MoveClass.BEST and r.loss == 0 and not r.missed_win


def test_delivering_mate_is_best_not_great():
    fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
    before = pe(fen, mate=-1, pv=["d8h4"], alt=(0, ["a7a6"]))
    after = pe(after_fen(fen, "d8h4"), final="0-1")
    r = classify_move(before, after, "d8h4", CFG)
    assert r.classification is MoveClass.BEST


def test_only_move_in_a_long_mate_is_great():
    before = pe(START, mate=5, pv=["d2d4"], alt=(0, ["e2e4"]))
    after = pe(after_fen(START, "d2d4"), mate=5)
    assert classify_move(before, after, "d2d4", CFG).classification is MoveClass.GREAT


# ---- unavailable data -------------------------------------------------------


def test_missing_evaluation_yields_no_classification():
    ok = pe(START, cp=30, pv=["e2e4"])
    gone = pe(after_fen(START, "e2e4"), unavailable=True)
    assert classify_move(ok, gone, "e2e4", CFG) is None
    assert classify_move(gone, ok, "e2e4", CFG) is None


# ---- great / brilliant ------------------------------------------------------

SAC_FEN = "4k3/6p1/8/8/8/8/8/3QK3 w - - 0 1"  # Qd7+ Kxd7 gives the queen for nothing
TRADE_FEN = "3r2k1/8/8/3q4/8/8/8/3QK3 w - - 0 1"  # Qxd5 Rxd5 is an even trade


def test_only_move_is_great():
    before = pe(START, cp=0, pv=["d2d4"], alt=(-300, ["e2e4"]))
    after = pe(after_fen(START, "d2d4"), cp=0)
    assert classify_move(before, after, "d2d4", CFG).classification is MoveClass.GREAT


def test_small_gap_to_second_best_is_just_best():
    before = pe(START, cp=0, pv=["d2d4"], alt=(-30, ["e2e4"]))
    after = pe(after_fen(START, "d2d4"), cp=0)
    assert classify_move(before, after, "d2d4", CFG).classification is MoveClass.BEST


def test_single_legal_move_is_never_great():
    before = pe(START, cp=0, pv=["d2d4"])  # no second line
    after = pe(after_fen(START, "d2d4"), cp=0)
    assert classify_move(before, after, "d2d4", CFG).classification is MoveClass.BEST


def test_no_great_when_game_already_decided():
    before = pe(START, cp=1000, pv=["d2d4"], alt=(-300, ["e2e4"]))  # ~97% win already
    after = pe(after_fen(START, "d2d4"), cp=1000)
    assert classify_move(before, after, "d2d4", CFG).classification is MoveClass.BEST


def test_queen_sacrifice_is_brilliant():
    before = pe(SAC_FEN, cp=150, pv=["d1d7"], alt=(-100, ["d1a4"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=150, pv=["e8d7", "e1e2", "g7g6"])
    r = classify_move(before, after, "d1d7", CFG)
    assert r.classification is MoveClass.BRILLIANT and r.is_sacrifice


def test_even_trade_is_great_not_brilliant():
    before = pe(TRADE_FEN, cp=0, pv=["d1d5"], alt=(-300, ["e1e2"]))
    after = pe(after_fen(TRADE_FEN, "d1d5"), cp=0, pv=["d8d5"])
    assert classify_move(before, after, "d1d5", CFG).classification is MoveClass.GREAT


def test_sacrifice_is_not_brilliant_when_the_best_alternative_already_wins():
    """Chess.com: you must not be 'completely winning even if you hadn't found the move'."""
    before = pe(SAC_FEN, cp=500, pv=["d1d7"], alt=(450, ["d1a4"]))  # both moves win (~85%)
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=500, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is MoveClass.BEST


def test_sacrifice_that_is_the_only_way_to_win_is_brilliant():
    before = pe(SAC_FEN, cp=500, pv=["d1d7"], alt=(-100, ["d1a4"]))  # top wins, alternative doesn't
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=500, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is MoveClass.BRILLIANT


def test_brilliant_does_not_need_an_only_move():
    # Alternative is only 4 points worse (no "Great" gap) but still not winning.
    before = pe(SAC_FEN, cp=150, pv=["d1d7"], alt=(100, ["d1a4"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=150, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is MoveClass.BRILLIANT


def test_a_sacrifice_leading_to_a_forced_mate_in_two_is_brilliant():
    """The smothered-mate pattern: the sacrifice itself is followed by mate in 2."""
    before = pe(SAC_FEN, cp=300, pv=["d1d7"], alt=(-100, ["d1a4"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), mate=2, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is MoveClass.BRILLIANT


def test_a_sacrifice_that_is_followed_by_immediate_mate_is_not_brilliant():
    before = pe(SAC_FEN, cp=300, pv=["d1d7"], alt=(-100, ["d1a4"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), mate=1, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is not MoveClass.BRILLIANT


def test_a_nearly_best_sacrifice_can_be_brilliant():
    # The engine's first choice is a different move, but the sacrifice is within ~0.4 points.
    before = pe(SAC_FEN, cp=150, pv=["d1a4"], alt=(145, ["d1d7"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=140, pv=["e8d7", "e1e2", "g7g6"])
    r = classify_move(before, after, "d1d7", CFG)
    assert r.classification is MoveClass.BRILLIANT and r.loss < CFG.excellent_loss


def test_a_sacrifice_that_loses_too_much_is_not_brilliant():
    before = pe(SAC_FEN, cp=150, pv=["d1a4"], alt=(145, ["d1d7"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=0, pv=["e8d7", "e1e2", "g7g6"])  # costs ~13 points
    assert classify_move(before, after, "d1d7", CFG).classification is MoveClass.MISTAKE


def test_brilliant_without_a_second_line_falls_back_to_the_position_evaluation():
    unwinning = pe(SAC_FEN, cp=150, pv=["d1d7"])  # multipv=1 and not winning yet
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=150, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(unwinning, after, "d1d7", CFG).classification is MoveClass.BRILLIANT
    winning = pe(SAC_FEN, cp=500, pv=["d1d7"])  # already ~86% with no way to compare
    assert classify_move(winning, after, "d1d7", CFG).classification is MoveClass.BEST


def test_sacrifice_leading_to_losing_position_is_not_brilliant():
    before = pe(SAC_FEN, cp=150, pv=["d1d7"], alt=(-100, ["d1a4"]))
    after = pe(after_fen(SAC_FEN, "d1d7"), cp=-200, pv=["e8d7", "e1e2", "g7g6"])
    assert classify_move(before, after, "d1d7", CFG).classification is not MoveClass.BRILLIANT


def test_is_sacrifice_detects_recovered_material():
    board = chess.Board(SAC_FEN)
    assert is_sacrifice(board, "d1d7", ("e8d7", "e1e2", "g7g6"), CFG)
    # Fabricated line where White wins the queen's worth back is not tested here (needs a
    # legal recapture); an empty / illegal follow-up must simply return False.
    assert not is_sacrifice(board, "d1d7", (), CFG)
    assert not is_sacrifice(board, "d1d7", ("a1b1",), CFG)  # illegal follow-up: stop safely


# ---- whole-game plumbing ----------------------------------------------------


def test_classify_game_requires_n_plus_one_positions():
    with pytest.raises(ValueError):
        classify_game([pe(START, cp=0)], ["e2e4"], CFG)


def test_summary_counts_only_classified_moves():
    p0 = pe(START, cp=30, pv=["e2e4"])
    f1 = after_fen(START, "e2e4")
    p1 = pe(f1, cp=30, pv=["e7e5"])
    p2 = pe(after_fen(f1, "e7e5"), unavailable=True)
    results = classify_game([p0, p1, p2], ["e2e4", "e7e5"], CFG)
    s = summarize([p0, p1, p2], results, CFG, complete=True)
    assert s["counts"]["white"]["best"] == 1
    assert sum(s["counts"]["black"].values()) == 0
    assert s["analyzed_moves"] == 1 and s["unanalyzed_moves"] == 1
    assert s["complete"] is False  # never claim a partially evaluated game is complete


def test_small_losses_are_not_key_positions():
    p0 = pe(START, cp=30, pv=["d2d4"])
    p1 = pe(after_fen(START, "a2a3"), cp=20, pv=["e7e5"])  # ~1 win% point: not notable
    results = classify_game([p0, p1], ["a2a3"], CFG)
    assert results[0].classification is MoveClass.EXCELLENT
    s = summarize([p0, p1], results, CFG, complete=True)
    assert s["key_positions"] == [] and s["swings"] == []


def test_summary_reports_swings_and_key_positions():
    p0 = pe(START, cp=100, pv=["d2d4"])
    p1 = pe(after_fen(START, "a2a3"), cp=-300, pv=["e7e5"])
    results = classify_game([p0, p1], ["a2a3"], CFG)
    s = summarize([p0, p1], results, CFG, complete=True)
    assert s["counts"]["white"]["blunder"] == 1
    assert s["swings"] and s["swings"][0]["ply"] == 1
    assert s["key_positions"][0]["ply"] == 1
    assert "large_loss" in s["key_positions"][0]["reasons"]
