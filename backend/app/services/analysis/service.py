"""API-side logic for requesting analysis (validation, cache reuse, queue limits)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import AnalysisJob, AnalysisRun
from app.models.game import Game
from app.services.analysis.engine import SearchLimit, get_engine_name
from app.services.analysis.store import find_completed_run, make_cache_key
from app.services.classification.config import ClassificationConfig
from app.services.jobs import queue


class AnalysisRequestError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class StartResult:
    job: AnalysisJob | None  # None when a cached review was reused
    run: AnalysisRun | None


def normalize_params(depth: int | None, nodes: int | None, multipv: int) -> dict:
    s = get_settings()
    if depth is None and nodes is None:
        depth = s.default_depth
    return {"depth": depth, "nodes": nodes, "multipv": multipv}


def start_analysis(
    db: Session, game: Game, depth: int | None, nodes: int | None, multipv: int
) -> StartResult:
    s = get_settings()
    params = normalize_params(depth, nodes, multipv)
    try:
        limit = SearchLimit(depth=params["depth"], nodes=params["nodes"]).validate()
    except ValueError as exc:
        raise AnalysisRequestError(422, str(exc)) from exc
    if not 1 <= multipv <= s.max_multipv:
        raise AnalysisRequestError(422, f"Engine lines must be between 1 and {s.max_multipv}.")
    if game.ply_count > s.max_plies:
        raise AnalysisRequestError(
            422, f"This game has {game.ply_count} plies; the analysis limit is {s.max_plies}."
        )

    try:
        engine_name = get_engine_name()
    except Exception as exc:
        raise AnalysisRequestError(503, "The analysis engine is unavailable.") from exc
    key = make_cache_key(engine_name, limit, multipv, ClassificationConfig().config_hash())

    # FR-02.7: reuse a completed review made with identical settings.
    cached = find_completed_run(db, game.id, key)
    if cached is not None:
        if game.current_analysis_id != cached.id:
            game.current_analysis_id = cached.id
            db.commit()
        return StartResult(job=None, run=cached)

    existing = queue.active_job_for_game(db, game.id)
    if existing is not None:
        if existing.params == params:
            return StartResult(job=existing, run=None)
        raise AnalysisRequestError(
            409, "An analysis of this game is already queued or running with different settings."
        )

    if queue.active_jobs_for_user(db, game.owner_id) >= s.max_active_jobs_per_user:
        raise AnalysisRequestError(
            429, f"You can have at most {s.max_active_jobs_per_user} analyses queued or running."
        )
    if queue.queued_total(db) >= s.max_queue_length:
        raise AnalysisRequestError(429, "The analysis queue is full. Please try again shortly.")

    job = AnalysisJob(
        game_id=game.id,
        owner_id=game.owner_id,
        status="queued",
        max_attempts=s.job_max_attempts,
        params=params,
        progress_done=0,
        progress_total=game.ply_count + 1,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request queued this game first (one active job per game is a DB rule).
        db.rollback()
        existing = db.scalar(
            select(AnalysisJob).where(
                AnalysisJob.game_id == game.id, AnalysisJob.status.in_(queue.ACTIVE)
            )
        )
        if existing is None:
            raise
        return StartResult(job=existing, run=None)
    return StartResult(job=job, run=None)
