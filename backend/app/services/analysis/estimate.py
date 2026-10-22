"""How long an analysis will take, and how long a job may run.

The cost model comes from measuring real games (see `python -m app.cli bench` and the table in the
README): per position, time grows about 1.5x per extra depth ply, and each extra engine line adds
about 1.2x the single-line cost. It is a ROUGH guide: how hard a game is to search varies a lot
with its content (forced mates are cheap), and so does the computer. The estimate is therefore
scaled by how long recent real runs took compared with the model.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.analysis import AnalysisRun
from app.models.game import Game

BASE_DEPTH = 12
BASE_SECONDS = 0.06  # one position, one line, depth 12
GROWTH_PER_PLY = 1.5
EXTRA_LINE_COST = 1.2
CALIBRATION_RUNS = 10
MIN_CALIBRATION_RUNS = 3
CALIBRATION_RANGE = (0.2, 5.0)

# Measured games took between 0.4x and 2.3x what the model predicts (how hard a game is to search
# depends on its content), so the honest answer is a range, not a single number.
UNCERTAINTY = 2.5


def seconds_per_position(depth: int, lines: int) -> float:
    per_line = 1 + EXTRA_LINE_COST * (lines - 1)
    return BASE_SECONDS * GROWTH_PER_PLY ** (depth - BASE_DEPTH) * per_line


def job_time_limit(positions: int, settings: Settings | None = None) -> float:
    """The most a job may run: the configured floor, or a fixed allowance per position if that is
    more, so a long game is not killed by a limit meant for runaway jobs. Still bounded: games are
    capped at MAX_PLIES and every single position at MAX_SECONDS_PER_POSITION."""
    s = settings or get_settings()
    return max(float(s.analysis_job_timeout_seconds), positions * s.job_seconds_per_position)


def calibration(db: Session) -> tuple[float, int]:
    """(factor, runs used): how much slower/faster than the model this server really is."""
    rows = db.execute(
        select(
            AnalysisRun.limit_depth,
            AnalysisRun.multipv,
            AnalysisRun.started_at,
            AnalysisRun.finished_at,
            Game.ply_count,
        )
        .join(Game, Game.id == AnalysisRun.game_id)
        .where(
            AnalysisRun.status == "completed",
            AnalysisRun.limit_depth.is_not(None),
            AnalysisRun.finished_at.is_not(None),
        )
        .order_by(AnalysisRun.finished_at.desc())
        .limit(CALIBRATION_RUNS)
    ).all()
    ratios = []
    for depth, lines, started, finished, plies in rows:
        actual = (finished - started).total_seconds()
        predicted = (plies + 1) * seconds_per_position(depth, lines)
        if actual > 0 and predicted > 0:
            ratios.append(actual / predicted)
    if len(ratios) < MIN_CALIBRATION_RUNS:
        return 1.0, len(ratios)
    low, high = CALIBRATION_RANGE
    return min(high, max(low, statistics.median(ratios))), len(ratios)


@dataclass
class Estimate:
    seconds: float | None  # central guess; None when the search is limited by nodes (not modelled)
    seconds_low: float | None
    seconds_high: float | None
    positions: int
    limit_seconds: float
    exceeds_limit: bool  # even the central guess is over the limit: it would almost certainly stop
    may_exceed_limit: bool  # the upper end of the range is over the limit: it might stop
    calibrated_from_runs: int


def estimate(
    db: Session, game: Game, depth: int | None, nodes: int | None, lines: int
) -> Estimate:
    positions = game.ply_count + 1
    limit = job_time_limit(positions)
    factor, used = calibration(db)
    if depth is None or nodes is not None:
        return Estimate(None, None, None, positions, limit, False, False, used)
    seconds = positions * seconds_per_position(depth, lines) * factor
    low, high = seconds / UNCERTAINTY, seconds * UNCERTAINTY
    return Estimate(seconds, low, high, positions, limit, seconds > limit, high > limit, used)
