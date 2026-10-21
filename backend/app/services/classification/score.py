"""Normalized evaluation types.

Every score in the system is stored from WHITE's perspective. "Unavailable" is
represented by the absence of a Score (None), never by a zero-valued Score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import chess
import chess.engine

_WIN_PCT_K = 0.00368208  # Lichess logistic constant
_CP_CLAMP = 1000


@dataclass(frozen=True)
class Score:
    """Exactly one of cp / mate / final is set.

    cp:    centipawns, positive = White better.
    mate:  moves to mate; positive = White mates, negative = Black mates (never 0).
    final: game-over result of a terminal position ("1-0", "0-1", "1/2-1/2").
    """

    cp: int | None = None
    mate: int | None = None
    final: str | None = None

    def __post_init__(self) -> None:
        if sum(v is not None for v in (self.cp, self.mate, self.final)) != 1:
            raise ValueError("Score needs exactly one of cp, mate, final")
        if self.mate == 0:
            raise ValueError("mate=0 is not representable; use final for terminal positions")
        if self.final not in (None, "1-0", "0-1", "1/2-1/2"):
            raise ValueError(f"bad final result {self.final!r}")

    @classmethod
    def from_pov(cls, pov: chess.engine.PovScore) -> Score:
        white = pov.white()
        if white.is_mate():
            mate = white.mate()
            if not mate:
                raise ValueError("engine reported mate 0 for a non-terminal position")
            return cls(mate=mate)
        cp = white.score()
        assert cp is not None
        return cls(cp=cp)

    @classmethod
    def from_outcome(cls, outcome: chess.Outcome) -> Score:
        return cls(final=outcome.result())

    @property
    def is_mate_like(self) -> bool:
        """True for forced mates and for checkmate itself."""
        return self.mate is not None or self.final in ("1-0", "0-1")

    def display(self) -> str:
        if self.final is not None:
            return self.final
        if self.mate is not None:
            return f"#{self.mate}" if self.mate > 0 else f"-#{-self.mate}"
        assert self.cp is not None
        return f"{self.cp / 100:+.2f}"


def win_pct_white(score: Score) -> float:
    """White's winning chances in [0, 100]."""
    if score.final is not None:
        return {"1-0": 100.0, "0-1": 0.0, "1/2-1/2": 50.0}[score.final]
    if score.mate is not None:
        return 100.0 if score.mate > 0 else 0.0
    assert score.cp is not None
    cp = max(-_CP_CLAMP, min(_CP_CLAMP, score.cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-_WIN_PCT_K * cp)) - 1.0)


def win_pct_for(score: Score, color: chess.Color) -> float:
    """Winning chances for `color`."""
    w = win_pct_white(score)
    return w if color == chess.WHITE else 100.0 - w


def favours(score: Score, color: chess.Color) -> bool:
    """True if `score` is a (forced) mate in favour of `color`."""
    if score.final is not None:
        return score.final == ("1-0" if color == chess.WHITE else "0-1")
    if score.mate is None:
        return False
    return (score.mate > 0) == (color == chess.WHITE)
