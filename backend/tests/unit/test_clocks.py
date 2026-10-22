import pytest

from app.services.clocks import game_clocks, parse_time_control, time_trouble_threshold

CLOCKED = """[Event "Blitz"]
[White "A"]
[Black "B"]
[TimeControl "180+2"]
[Result "1-0"]

1. e4 {[%clk 0:03:01]} e5 {[%clk 0:03:00]} 2. Nf3 {[%clk 0:02:50]} Nc6 {[%clk 0:00:15]} 3. Bb5 {[%clk 0:02:48]} 1-0
"""

PLAIN = """[White "A"]
[Black "B"]
[Result "1-0"]

1. e4 e5 2. Nf3 1-0
"""


@pytest.mark.parametrize(
    "value,expected",
    [("600", (600.0, 0.0)), ("180+2", (180.0, 2.0)), ("1/86400", None), ("-", None), ("?", None), (None, None)],
)
def test_parse_time_control(value, expected):
    assert parse_time_control(value) == expected


def test_threshold_is_ten_percent_capped_at_thirty_seconds():
    assert time_trouble_threshold(60) == 6
    assert time_trouble_threshold(180) == 18
    assert time_trouble_threshold(600) == 30
    assert time_trouble_threshold(None) == 30


def test_time_spent_uses_increment_and_base():
    clocks = game_clocks(CLOCKED, "180+2")
    assert [c["ply"] for c in clocks] == [1, 2, 3, 4, 5]
    # 1.e4: starts with 180, +2 increment, 181 left -> 1 s used
    assert clocks[0]["clock"] == 181 and clocks[0]["spent"] == 1.0
    assert clocks[1]["spent"] == 2.0  # 180 + 2 - 180
    assert clocks[2]["spent"] == 181 + 2 - 170  # white's second move: 13 s
    assert clocks[3]["clock"] == 15 and clocks[3]["spent"] == 167.0
    assert clocks[3]["time_trouble"] is True and clocks[2]["time_trouble"] is False


def test_game_without_clocks_has_none_not_zeros():
    assert game_clocks(PLAIN, None) is None


def test_unknown_time_control_still_gives_clocks_but_no_first_move_time():
    clocks = game_clocks(CLOCKED, None)
    assert clocks[0]["clock"] == 181 and clocks[0]["spent"] is None
    assert clocks[2]["spent"] == 11.0  # 181 + 0 - 170, no increment known
