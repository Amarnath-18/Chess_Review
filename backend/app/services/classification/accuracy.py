"""Game accuracy, in the style of Lichess's published method.

Each move gets an accuracy from the win% it cost, and a side's game accuracy blends a
volatility-weighted mean (moves in sharp, swingy stretches count more) with a harmonic mean
(which punishes a few very bad moves). It is this app's number: it will not match Chess.com's
"accuracy", whose formula is not published.
"""
from __future__ import annotations

import math
import statistics

# Lichess's published fit of move accuracy against win% lost.
_A, _B, _C = 103.1668, -0.04354, -3.1669
_MIN_WEIGHT, _MAX_WEIGHT = 0.5, 12.0


def move_accuracy(win_loss: float) -> float:
    """Accuracy in [0, 100] of a move that lost `win_loss` win% points (0 = no loss)."""
    acc = _A * math.exp(_B * max(0.0, win_loss)) + _C + 1  # +1: the "uncertainty" bonus
    return max(0.0, min(100.0, acc))


def _weights(win_white: list[float | None], n_moves: int) -> list[float]:
    """Volatility weight per move: stdev of win% in a window around it, clamped."""
    values = [w if w is not None else 50.0 for w in win_white]
    size = max(2, min(8, len(values) // 10))
    padded = [values[0]] * (size - 2) + values  # so early moves get a full window
    out = []
    for i in range(n_moves):
        window = padded[i : i + size]
        if len(window) < 2:
            out.append(_MIN_WEIGHT)
            continue
        out.append(max(_MIN_WEIGHT, min(_MAX_WEIGHT, statistics.pstdev(window))))
    return out


def game_accuracy(
    win_white: list[float | None],
    losses: list[float | None],
    movers_white: list[bool],
) -> dict[str, float | None]:
    """`win_white` has one entry per position (n + 1), `losses` and `movers_white` one per move (n).

    A loss of None means that move was not evaluated; it is left out, and a side with no
    evaluated moves has accuracy None (never 0 or 100).
    """
    n = len(losses)
    if len(win_white) != n + 1 or len(movers_white) != n:
        raise ValueError("need n+1 positions for n moves")
    if n == 0:
        return {"white": None, "black": None}
    weights = _weights(win_white, n)
    result: dict[str, float | None] = {}
    for side, is_white in (("white", True), ("black", False)):
        accs, ws = [], []
        for i in range(n):
            if movers_white[i] == is_white and losses[i] is not None:
                accs.append(move_accuracy(losses[i]))
                ws.append(weights[i])
        if not accs:
            result[side] = None
            continue
        weighted = sum(a * w for a, w in zip(accs, ws)) / sum(ws)
        harmonic = len(accs) / sum(1.0 / max(a, 1e-6) for a in accs)
        result[side] = round((weighted + harmonic) / 2, 1)
    return result
