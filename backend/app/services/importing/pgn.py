"""PGN parsing and validation. Never raises on bad game content; returns per-game failures."""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date

import chess
import chess.pgn

MAX_PGN_BYTES = 1_000_000
MAX_GAMES_PER_IMPORT = 50
_RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
_UNKNOWN = {"", "?", "??", "-", "????.??.??"}


class ImportLimitError(ValueError):
    """The whole request is unacceptable (too large, too many games, nothing found)."""


@dataclass(frozen=True)
class ParsedGame:
    index: int  # 1-based position within the submitted text
    pgn: str
    fingerprint: str
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    played_at: date | None
    time_control: str | None
    opening_name: str | None
    eco: str | None
    event: str | None
    ply_count: int
    moves_uci: tuple[str, ...]


@dataclass(frozen=True)
class ParseFailure:
    index: int
    message: str


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if value in _UNKNOWN else value[:limit]


def _int(value: str | None) -> int | None:
    if value and value.strip().isdigit():
        n = int(value.strip())
        return n if 0 < n < 10_000 else None
    return None


def _date(headers: chess.pgn.Headers) -> date | None:
    raw = headers.get("Date") or headers.get("UTCDate") or ""
    m = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", raw.strip())
    if not m:
        return None  # partial dates ("2024.??.??") are treated as unknown
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def fingerprint(white: str, black: str, played_at: date | None, start_fen: str | None,
                moves_uci: tuple[str, ...]) -> str:
    parts = [
        white.lower(),
        black.lower(),
        played_at.isoformat() if played_at else "",
        start_fen or "",
        " ".join(moves_uci),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _describe_error(game: chess.pgn.Game, index: int) -> str:
    err = game.errors[0]
    moves = list(game.mainline_moves())
    board = game.board()
    for m in moves:
        board.push(m)
    # The board is now at the position where the unreadable move was expected.
    dots = "." if board.turn == chess.WHITE else "..."
    token = re.search(r"'([^']+)'", str(err))
    what = f" {token[1]!r}" if token else ""
    return (
        f"Game {index}: illegal or unreadable move{what} at move "
        f"{board.fullmove_number}{dots} — the moves before it were read successfully."
    )


def _parse_one(game: chess.pgn.Game, index: int) -> ParsedGame | ParseFailure:
    try:
        board = game.board()
    except ValueError as exc:
        return ParseFailure(index, f"Game {index}: unsupported or invalid setup ({exc})")
    if board.uci_variant != "chess" or board.chess960:
        return ParseFailure(index, f"Game {index}: only standard chess is supported")
    if game.errors:
        return ParseFailure(index, _describe_error(game, index))

    moves = tuple(m.uci() for m in game.mainline_moves())
    if not moves:
        return ParseFailure(index, f"Game {index}: the game has no moves")

    h = game.headers
    white = _clean(h.get("White"), 100) or "?"
    black = _clean(h.get("Black"), 100) or "?"
    result = h.get("Result", "*").strip()
    played_at = _date(h)
    start_fen = game.board().fen() if "FEN" in h else None
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return ParsedGame(
        index=index,
        pgn=game.accept(exporter),
        fingerprint=fingerprint(white, black, played_at, start_fen, moves),
        white=white,
        black=black,
        white_elo=_int(h.get("WhiteElo")),
        black_elo=_int(h.get("BlackElo")),
        result=result if result in _RESULTS else "*",
        played_at=played_at,
        time_control=_clean(h.get("TimeControl"), 32),
        opening_name=_clean(h.get("Opening"), 200),
        eco=_clean(h.get("ECO"), 8),
        event=_clean(h.get("Event"), 200),
        ply_count=len(moves),
        moves_uci=moves,
    )


def parse_pgn(text: str, max_games: int = MAX_GAMES_PER_IMPORT) -> list[ParsedGame | ParseFailure]:
    text = text.replace("\x00", "")
    if not text.strip():
        raise ImportLimitError("No PGN text was provided.")
    handle = io.StringIO(text)
    out: list[ParsedGame | ParseFailure] = []
    while True:
        index = len(out) + 1
        try:
            game = chess.pgn.read_game(handle)
        except Exception as exc:  # python-chess is lenient, but never let one game kill the batch
            out.append(ParseFailure(index, f"Game {index}: unreadable PGN ({exc})"))
            break
        if game is None:
            break
        if index > max_games:
            raise ImportLimitError(f"Too many games in one import (the limit is {max_games}).")
        out.append(_parse_one(game, index))
    if not out:
        raise ImportLimitError("No games were found in the PGN text.")
    return out
