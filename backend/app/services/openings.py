"""Opening names and "book" detection from the open Lichess chess-openings dataset (CC0).

Positions are looked up without move counters, so a transposition into a known opening is
recognised too.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import chess

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "openings"
_MOVE_NUMBER = re.compile(r"\d+\.(\.\.)?")


def position_key(board: chess.Board) -> str:
    """Placement, side to move, castling rights (no en passant square, no move counters)."""
    return " ".join(board.fen().split()[:3])


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, tuple[str, str]], set[str]]:
    """(named positions, every position on the way to one). The dataset only names some
    positions, but every move along a named line is theory, so the whole path counts as book."""
    named: dict[str, tuple[str, str]] = {}
    path_positions: set[str] = set()
    for path in sorted(DATA_DIR.glob("*.tsv")):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            eco, name, pgn = parts
            board = chess.Board()
            keys = []
            try:
                for token in _MOVE_NUMBER.sub(" ", pgn).split():
                    board.push_san(token)
                    keys.append(position_key(board))
            except ValueError:
                continue  # a line the dataset gets wrong is skipped, never fatal
            path_positions.update(keys)
            # the first entry wins; later, longer names for the same position do not replace it
            named.setdefault(keys[-1], (eco, name))
    return named, path_positions


def lookup(board: chess.Board) -> tuple[str, str] | None:
    """(ECO code, opening name) if this exact position is named in the dataset."""
    return _tables()[0].get(position_key(board))


def book_run(start_fen: str, fens_after: list[str]) -> list[tuple[str, str] | None]:
    """For each position after a move: the opening (the latest named one so far) while the game
    has stayed on a known line, else None.

    Once a move leaves book, later positions are not book even if the game transposes back.
    Games that do not start from the standard position have no book.
    """
    named, on_path = _tables()
    out: list[tuple[str, str] | None] = []
    in_book = chess.Board(start_fen).fen().split()[:3] == chess.Board().fen().split()[:3]
    current: tuple[str, str] | None = None
    for fen in fens_after:
        key = " ".join(fen.split()[:3])
        # a move that ends the game (e.g. Fool's Mate is in the dataset) is a result, not theory
        if in_book and key in on_path and not chess.Board(fen).is_game_over():
            current = named.get(key, current)
            out.append(current)
        else:
            in_book = False
            out.append(None)
    return out
