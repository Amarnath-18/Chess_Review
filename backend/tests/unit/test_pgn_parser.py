from datetime import date

import pytest

from app.services.importing.pgn import (
    ImportLimitError,
    ParsedGame,
    ParseFailure,
    parse_pgn,
)

GOOD = """[Event "Casual"]
[Site "?"]
[Date "2024.03.09"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[WhiteElo "1500"]
[BlackElo "?"]
[TimeControl "600+5"]
[ECO "C50"]
[Opening "Italian Game"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""


def only(text: str) -> ParsedGame:
    (item,) = parse_pgn(text)
    assert isinstance(item, ParsedGame), item
    return item


def test_metadata_extraction():
    g = only(GOOD)
    assert (g.white, g.black, g.result) == ("Alice", "Bob", "1-0")
    assert g.white_elo == 1500 and g.black_elo is None  # "?" is unknown, not 0
    assert g.played_at == date(2024, 3, 9)
    assert g.time_control == "600+5" and g.eco == "C50" and g.opening_name == "Italian Game"
    assert g.ply_count == 6 == len(g.moves_uci)


def test_unknown_and_partial_dates_are_none():
    assert only(GOOD.replace("2024.03.09", "????.??.??")).played_at is None
    assert only(GOOD.replace("2024.03.09", "2024.03.??")).played_at is None


def test_fingerprint_ignores_irrelevant_headers_but_not_moves():
    a = only(GOOD)
    b = only(GOOD.replace('"Casual"', '"Some other event"').replace("C50", "C54"))
    c = only(GOOD.replace("3. Bc4 Bc5", "3. Bb5 a6"))
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


def test_illegal_move_gives_a_located_error():
    (item,) = parse_pgn(GOOD.replace("2. Nf3", "2. Ke3"))
    assert isinstance(item, ParseFailure)
    assert "Ke3" in item.message and "move 2." in item.message


def test_garbage_is_a_failure_not_a_crash():
    (item,) = parse_pgn("this is not chess")
    assert isinstance(item, ParseFailure)


def test_empty_input_is_rejected():
    with pytest.raises(ImportLimitError):
        parse_pgn("   \n  ")


def test_game_without_moves_is_a_failure():
    (item,) = parse_pgn('[White "A"]\n[Black "B"]\n[Result "*"]\n\n*\n')
    assert isinstance(item, ParseFailure) and "no moves" in item.message


def test_non_standard_variants_are_rejected():
    (item,) = parse_pgn('[Variant "Chess960"]\n\n1. e4 e5 *\n')
    assert isinstance(item, ParseFailure)
    (item,) = parse_pgn('[Variant "Atomic"]\n\n1. e4 e5 *\n')
    assert isinstance(item, ParseFailure)


def test_multiple_games_with_a_bad_one_in_the_middle():
    text = GOOD + "\n" + GOOD.replace("2. Nf3", "2. Ke3") + "\n" + GOOD.replace("Alice", "Carol")
    items = parse_pgn(text)
    assert [type(i) for i in items] == [ParsedGame, ParseFailure, ParsedGame]
    assert [i.index for i in items] == [1, 2, 3]


def test_game_count_limit():
    with pytest.raises(ImportLimitError):
        parse_pgn(GOOD * 3, max_games=2)


def test_nul_bytes_are_stripped():
    assert only(GOOD.replace("Alice", "Ali\x00ce")).white == "Alice"
