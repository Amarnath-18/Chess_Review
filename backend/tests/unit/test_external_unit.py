import pytest

from app.services.importing.external import ExternalError, parse_game_url, validate_username
from app.services.importing.pgn import opening_from_eco_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://lichess.org/HqjDTU4A", ("lichess", "HqjDTU4A")),
        ("https://lichess.org/HqjDTU4A/black", ("lichess", "HqjDTU4A")),
        ("http://lichess.org/HqjDTU4A#12", ("lichess", "HqjDTU4A")),
        ("https://lichess.org/HqjDTU4AwxYz", ("lichess", "HqjDTU4A")),  # 12-char player view
        (" https://lichess.org/HqjDTU4A ", ("lichess", "HqjDTU4A")),
        ("https://www.chess.com/game/live/183193101523", ("chesscom", "183193101523")),
        ("https://chess.com/game/live/183193101523?username=x", ("chesscom", "183193101523")),
        ("https://www.chess.com/game/daily/777777", ("chesscom", "777777")),
        ("https://www.chess.com/analysis/game/live/183193101523?tab=review", ("chesscom", "183193101523")),
        ("https://www.chess.com/live/game/183193101523", ("chesscom", "183193101523")),
        ("https://www.chess.com/daily/game/777777", ("chesscom", "777777")),
    ],
)
def test_recognised_game_links(url, expected):
    assert parse_game_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://lichess.org/",
        "https://lichess.org/abc",  # too short to be a game id
        "https://evil.com/game/live/183193101523",
        "https://chess.com.evil.com/game/live/183193101523",
        "https://lichess.org.evil.io/HqjDTU4A",
        "https://evil.com/?u=https://lichess.org/HqjDTU4A",
        "https://user@lichess.org@evil.com/HqjDTU4A",
        "ftp://lichess.org/HqjDTU4A",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://www.chess.com/member/hikaru",
        "https://www.chess.com/game/live/abc",
        "https://www.chess.com/game/live/1",  # too short
    ],
)
def test_other_links_are_refused(url):
    with pytest.raises(ExternalError) as err:
        parse_game_url(url)
    assert err.value.status_code == 422


@pytest.mark.parametrize(
    "source, name",
    [("chesscom", "hikaru"), ("chesscom", "A_b-c9"), ("lichess", "DrNykterstein"), ("lichess", "ab")],
)
def test_valid_usernames(source, name):
    assert validate_username(source, f"  {name} ") == name


@pytest.mark.parametrize(
    "source, name",
    [
        ("chesscom", "ab"),  # Chess.com needs at least 3 characters
        ("chesscom", "x" * 26),
        ("lichess", "x"),
        ("lichess", "x" * 31),
        ("chesscom", "has space"),
        ("lichess", "../etc/passwd"),
        ("chesscom", "user;drop table"),
        ("lichess", "name?x=1"),
        ("chesscom", "ünïcode"),
        ("lichess", ""),
    ],
)
def test_invalid_usernames(source, name):
    with pytest.raises(ExternalError) as err:
        validate_username(source, name)
    assert err.value.status_code == 422


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.chess.com/openings/Alapin-Sicilian-Defense-2...Qa5", "Alapin Sicilian Defense"),
        ("https://www.chess.com/openings/Sicilian-Defense-Najdorf-Variation-6.Be3", "Sicilian Defense Najdorf Variation"),
        ("https://www.chess.com/openings/Italian-Game", "Italian Game"),
        ("https://www.chess.com/openings/Italian-Game/", "Italian Game"),
        ("https://www.chess.com/openings/Nimzowitsch-Defense-1...Nc6", "Nimzowitsch Defense"),
        ("", None),
        (None, None),
    ],
)
def test_opening_name_from_chesscom_eco_url(url, expected):
    assert opening_from_eco_url(url) == expected
