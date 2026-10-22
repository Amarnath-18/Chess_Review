import pytest

from app.services.classification.accuracy import game_accuracy, move_accuracy


def test_no_loss_is_near_perfect():
    assert move_accuracy(0) == pytest.approx(100.0, abs=0.01)


def test_accuracy_falls_with_loss_and_stays_in_range():
    values = [move_accuracy(x) for x in (0, 2, 5, 10, 20, 40, 100)]
    assert values == sorted(values, reverse=True)
    assert all(0 <= v <= 100 for v in values)
    # hand-computed: 103.1668*exp(-0.4354) - 3.1669 + 1 = 66.75 - 2.17 = 64.6
    assert move_accuracy(10) == pytest.approx(64.6, abs=0.1)
    assert move_accuracy(100) < 5


def test_perfect_game_scores_100_and_a_blunder_costs_a_lot():
    wins = [50.0] * 7
    perfect = game_accuracy(wins, [0.0] * 6, [True, False] * 3)
    assert perfect == {"white": 100.0, "black": 100.0}
    flawed = game_accuracy(wins, [0.0, 0.0, 30.0, 0.0, 0.0, 0.0], [True, False] * 3)
    assert flawed["white"] < 80
    assert flawed["black"] == 100.0


def test_unevaluated_moves_are_left_out_and_empty_side_is_none():
    out = game_accuracy([50.0, 50.0, 50.0], [None, 0.0], [True, False])
    assert out["white"] is None  # never 0 or 100 for "no data"
    assert out["black"] == 100.0


def test_length_mismatch_rejected():
    with pytest.raises(ValueError):
        game_accuracy([50.0], [0.0], [True])
