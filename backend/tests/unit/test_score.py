import chess
import chess.engine
import pytest

from app.services.classification.config import ClassificationConfig
from app.services.classification.score import Score, favours, win_pct_for, win_pct_white


def test_score_requires_exactly_one_field():
    with pytest.raises(ValueError):
        Score()
    with pytest.raises(ValueError):
        Score(cp=1, mate=2)
    with pytest.raises(ValueError):
        Score(mate=0)
    with pytest.raises(ValueError):
        Score(final="2-0")


def test_zero_cp_is_a_real_value_distinct_from_unavailable():
    assert Score(cp=0).cp == 0
    assert win_pct_white(Score(cp=0)) == pytest.approx(50.0)


@pytest.mark.parametrize("cp", [0, 30, 100, 300, 800, 5000])
def test_win_pct_is_symmetric(cp):
    assert win_pct_white(Score(cp=cp)) + win_pct_white(Score(cp=-cp)) == pytest.approx(100.0)


def test_win_pct_is_monotonic_and_bounded():
    values = [win_pct_white(Score(cp=cp)) for cp in range(-1500, 1501, 50)]
    assert values == sorted(values)
    assert 0 < values[0] and values[-1] < 100


def test_mate_and_final_scores():
    assert win_pct_white(Score(mate=3)) == 100.0
    assert win_pct_white(Score(mate=-1)) == 0.0
    assert win_pct_white(Score(final="1-0")) == 100.0
    assert win_pct_white(Score(final="0-1")) == 0.0
    assert win_pct_white(Score(final="1/2-1/2")) == 50.0


def test_perspective_flip():
    s = Score(cp=200)
    assert win_pct_for(s, chess.WHITE) + win_pct_for(s, chess.BLACK) == pytest.approx(100.0)
    assert win_pct_for(s, chess.WHITE) > 50 > win_pct_for(s, chess.BLACK)


def test_favours():
    assert favours(Score(mate=2), chess.WHITE)
    assert not favours(Score(mate=2), chess.BLACK)
    assert favours(Score(mate=-2), chess.BLACK)
    assert favours(Score(final="0-1"), chess.BLACK)
    assert not favours(Score(cp=900), chess.WHITE)


def test_from_pov_normalizes_to_white():
    # PovScore is relative to `turn`; the stored score must always be White's view.
    assert Score.from_pov(chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE)).cp == 50
    assert Score.from_pov(chess.engine.PovScore(chess.engine.Cp(50), chess.BLACK)).cp == -50
    assert Score.from_pov(chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)).mate == 3
    assert Score.from_pov(chess.engine.PovScore(chess.engine.Mate(2), chess.BLACK)).mate == -2
    assert Score.from_pov(chess.engine.PovScore(chess.engine.Mate(-3), chess.BLACK)).mate == 3


def test_display():
    assert Score(cp=83).display() == "+0.83"
    assert Score(cp=-120).display() == "-1.20"
    assert Score(mate=3).display() == "#3"
    assert Score(mate=-2).display() == "-#2"


def test_config_hash_tracks_values_and_rejects_unknown_keys():
    a = ClassificationConfig()
    assert a.config_hash() == ClassificationConfig().config_hash()
    assert a.config_hash() != ClassificationConfig(blunder_loss=25).config_hash()
    with pytest.raises(ValueError):
        ClassificationConfig.from_dict({"nope": 1})
    assert ClassificationConfig.from_dict({"blunder_loss": 25}).blunder_loss == 25
