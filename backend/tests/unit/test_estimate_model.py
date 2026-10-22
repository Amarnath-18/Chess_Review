import pytest

from app.config import get_settings
from app.services.analysis.estimate import (
    UNCERTAINTY,
    job_time_limit,
    seconds_per_position,
)

# Real timings: (positions, depth, lines, seconds). Measured with `python -m app.cli bench` on real
# Lichess games (40, 80 and 151 plies) with Stockfish 17.1, one thread. See the README for the table.
MEASURED = [
    (41, 12, 1, 2.6), (41, 12, 3, 6.3), (41, 16, 1, 11.3), (41, 16, 3, 39.4),
    (41, 20, 1, 39.8), (41, 20, 3, 137.4),
    (81, 12, 1, 5.1), (81, 12, 3, 17.5), (81, 16, 1, 27.7), (81, 16, 3, 88.7),
    (81, 20, 1, 144.8), (81, 20, 3, 955.3),
    (152, 12, 1, 9.6), (152, 12, 3, 17.7), (152, 16, 1, 36.5), (152, 16, 3, 97.1),
    (152, 20, 1, 125.2), (152, 20, 3, 436.5),
]


def test_cost_grows_with_depth_and_with_lines():
    for lines in (1, 3, 5):
        costs = [seconds_per_position(d, lines) for d in range(8, 23)]
        assert costs == sorted(costs) and len(set(costs)) == len(costs)
    for depth in (10, 16, 22):
        costs = [seconds_per_position(depth, n) for n in range(1, 6)]
        assert costs == sorted(costs) and len(set(costs)) == len(costs)


def test_every_measured_run_falls_inside_the_range_we_show():
    """The range is what we promise users, so it must contain what really happened."""
    for positions, depth, lines, actual in MEASURED:
        guess = positions * seconds_per_position(depth, lines)
        assert guess / UNCERTAINTY <= actual <= guess * UNCERTAINTY, (positions, depth, lines, actual, guess)


def test_the_central_guess_is_usually_close():
    close = sum(
        0.6 < positions * seconds_per_position(depth, lines) / actual < 1.6
        for positions, depth, lines, actual in MEASURED
    )
    assert close >= len(MEASURED) * 0.7  # most runs within about 60%; the rest are what the range is for


def test_the_range_is_not_uselessly_wide():
    assert UNCERTAINTY <= 3


def test_the_documented_default_is_a_reasonable_wait():
    default = get_settings()
    per_position = seconds_per_position(default.default_depth, default.default_multipv)
    assert 81 * per_position < 180  # an 80-move game at the defaults: under three minutes


def test_the_time_limit_has_a_floor_and_grows_with_the_game():
    s = get_settings().model_copy(update={"analysis_job_timeout_seconds": 600, "job_seconds_per_position": 15})
    assert job_time_limit(20, s) == 600  # short game: the floor
    assert job_time_limit(151, s) == 2265  # long game: 15 s per position
    assert job_time_limit(301, s) == 4515
    assert job_time_limit(151, s) > job_time_limit(20, s)


def test_the_limit_can_be_a_flat_value():
    s = get_settings().model_copy(update={"analysis_job_timeout_seconds": 600, "job_seconds_per_position": 0})
    assert job_time_limit(500, s) == 600


def test_the_slowest_measured_run_would_not_have_been_stopped_at_the_default():
    """80-move game, depth 20, 3 lines: 955 s. The default allowance must let that finish."""
    s = get_settings()
    assert job_time_limit(81, s) > 955


def test_a_deep_many_line_search_on_a_long_game_exceeds_the_limit():
    """The case the estimate exists to warn about."""
    s = get_settings()
    positions = 151
    assert positions * seconds_per_position(22, 5) > job_time_limit(positions, s)
    assert positions * seconds_per_position(16, 3) < job_time_limit(positions, s)


@pytest.mark.parametrize("depth", [1, 12, 22])
def test_costs_are_positive(depth):
    assert seconds_per_position(depth, 1) > 0
