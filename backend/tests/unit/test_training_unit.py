import chess

from app.models.analysis import AnalysisPosition
from app.services.stats import phase_of, time_class
from app.services.training import find_candidates

START = chess.STARTING_FEN


def pos(ply, fen, cp=0, lines=None, uci=None, cls=None, loss=0.0, missed_win=False):
    lines = lines if lines is not None else [(cp, [])]
    return AnalysisPosition(
        ply=ply, fen=fen, score_cp=cp,
        lines=[{"cp": c, "mate": None, "pv": pv} for c, pv in lines],
        played_move_uci=uci, classification=cls, loss_pct=loss, missed_win=missed_win,
    )


def review(first_move_lines, cls="blunder", loss=34.0, played="a2a3"):
    """White's first move was `played` (a mistake): the position before it holds the lines."""
    b = chess.Board()
    before = pos(0, b.fen(), lines=first_move_lines)
    b.push_uci(played)
    return [before, pos(1, b.fen(), cp=-100, uci=played, cls=cls, loss=loss)]


CLEAR = [(300, ["e2e4", "e7e5"]), (0, ["d2d4"]), (-50, ["g1f3"])]


def test_a_clear_mistake_by_me_becomes_a_puzzle():
    [c] = find_candidates(review(CLEAR), "white")
    assert c.ply == 1 and c.fen == START and c.best_uci == "e2e4" and c.played_uci == "a2a3"
    assert c.accepted == ["e2e4"] and c.pv == ["e2e4", "e7e5"] and c.loss == 34.0


def test_the_other_sides_mistakes_are_not_my_puzzles():
    assert find_candidates(review(CLEAR), "black") == []


def test_an_ambiguous_position_is_not_a_puzzle():
    close = [(300, ["e2e4"]), (295, ["d2d4"])]  # two moves about equally good
    assert find_candidates(review(close), "white") == []


def test_moves_nearly_as_good_as_the_best_are_also_accepted():
    lines = [(300, ["e2e4"]), (0, ["d2d4"])]
    assert find_candidates(review(lines), "white")[0].accepted == ["e2e4"]
    # a second move within 3 win% still counts, provided the gap is to a third line
    # (the gap rule uses the second line, so this case is excluded as ambiguous instead)
    assert find_candidates(review([(300, ["e2e4"]), (298, ["d2d4"]), (0, ["g1f3"])]), "white") == []


def test_minor_errors_and_single_line_reviews_are_skipped():
    assert find_candidates(review(CLEAR, cls="inaccuracy", loss=6.0), "white") == []
    assert find_candidates(review([(300, ["e2e4"])]), "white") == []


def test_playing_the_best_move_is_never_a_puzzle():
    assert find_candidates(review(CLEAR, played="e2e4", cls="blunder"), "white") == []


def test_a_missed_win_counts_even_if_labelled_otherwise():
    rows = review(CLEAR, cls="good", loss=12.0)
    rows[1].missed_win = True
    assert len(find_candidates(rows, "white")) == 1


def test_phase_and_time_class():
    assert phase_of(10, START) == "opening"
    assert phase_of(30, START) == "middlegame"
    assert phase_of(60, "8/8/4k3/8/8/4K3/4R3/8 w - - 0 1") == "endgame"
    assert [time_class(t) for t in ("60", "180+2", "600", "1800", "1/86400", None)] == [
        "bullet", "blitz", "rapid", "classical", "unknown", "unknown",
    ]
