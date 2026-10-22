"""Clock times from `[%clk h:mm:ss]` move comments (Chess.com and Lichess PGNs carry them).

Nothing is invented: a game without clocks yields None, and a move whose time cannot be worked
out has `spent` None rather than 0.
"""
from __future__ import annotations

import io
import re

import chess.pgn

TIME_TROUBLE_SECONDS = 30.0
TIME_TROUBLE_FRACTION = 0.10


def parse_time_control(value: str | None) -> tuple[float, float] | None:
    """(base seconds, increment seconds) from a PGN TimeControl such as "600", "180+2", "40/7200:300".

    Daily and untimed formats ("1/86400", "-", "?") return None.
    """
    if not value:
        return None
    m = re.fullmatch(r"(\d+)(?:\+(\d+))?", value.strip())
    if not m:
        return None
    return float(m[1]), float(m[2] or 0)


def time_trouble_threshold(base: float | None) -> float:
    """Remaining seconds under which a side is "in time trouble": 10% of the starting time,
    but never more than 30 s (so a 3-minute game flags at 18 s and a 10-minute game at 30 s)."""
    if base is None:
        return TIME_TROUBLE_SECONDS
    return min(TIME_TROUBLE_SECONDS, TIME_TROUBLE_FRACTION * base)


def game_clocks(pgn: str, time_control: str | None) -> list[dict] | None:
    """Per ply: {ply, clock, spent, time_trouble}, or None when the game has no clock comments.

    `clock` is the mover's remaining time after the move. `spent` = previous clock of that side
    + increment - clock (for a side's first move, the base time stands in for the previous clock).
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return None
    clocks = [node.clock() for node in game.mainline()]
    if not any(c is not None for c in clocks):
        return None

    tc = parse_time_control(time_control)
    base, inc = tc if tc else (None, 0.0)
    threshold = time_trouble_threshold(base)
    white_first = game.board().turn == chess.WHITE
    previous: dict[bool, float | None] = {True: base, False: base}
    out: list[dict] = []
    for i, clock in enumerate(clocks):
        mover_white = (i % 2 == 0) == white_first
        before = previous[mover_white]
        spent = None
        if clock is not None and before is not None:
            spent = max(0.0, before + inc - clock)
        if clock is not None:
            previous[mover_white] = clock
        out.append(
            {
                "ply": i + 1,
                "clock": clock,
                "spent": round(spent, 1) if spent is not None else None,
                "time_trouble": clock is not None and clock < threshold,
            }
        )
    return out
