"""Analyze-all: many games as one cancellable unit.

A batch keeps only a few of its games in the job queue at a time (never the person's last free
slot), so it neither floods the queue nor locks the person out of analysing a single game.
`advance` is called when a batch is created and then by the worker's maintenance loop.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import AnalysisJob
from app.models.base import utcnow
from app.models.batch import AnalysisBatch, BatchGame
from app.models.game import Game
from app.models.user import User
from app.services import user_settings
from app.services.analysis.engine import SearchLimit
from app.services.analysis.estimate import estimate as estimate_game
from app.services.analysis.service import AnalysisRequestError, normalize_params, start_analysis
from app.services.jobs import queue

log = logging.getLogger("worker")

RUNNING = "running"


class BatchError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def feed_limit() -> int:
    """How many of a batch's games may be queued or running at once: one less than the person's
    limit, so a single game can still be analysed while a batch runs."""
    return max(1, get_settings().max_active_jobs_per_user - 1)


def validate_params(depth: int | None, nodes: int | None, multipv: int) -> dict:
    s = get_settings()
    params = normalize_params(depth, nodes, multipv)
    try:
        SearchLimit(depth=params["depth"], nodes=params["nodes"]).validate()
    except ValueError as exc:
        raise BatchError(422, str(exc)) from exc
    if not 1 <= multipv <= s.max_multipv:
        raise BatchError(422, f"Engine lines must be between 1 and {s.max_multipv}.")
    return params


def running_batch(db: Session, owner_id: uuid.UUID) -> AnalysisBatch | None:
    return db.scalar(
        select(AnalysisBatch).where(
            AnalysisBatch.owner_id == owner_id, AnalysisBatch.status == RUNNING
        )
    )


def skip_reason(db: Session, game: Game, params: dict) -> str | None:
    """Why a game cannot be part of a batch with these settings (None = it can)."""
    s = get_settings()
    if game.ply_count > s.max_plies:
        return f"Too long ({game.ply_count} plies; the limit is {s.max_plies})."
    est = estimate_game(db, game, params["depth"], params["nodes"], params["multipv"])
    if est.exceeds_limit:
        return "Would take longer than the time limit at these settings."
    return None


@dataclass
class BatchPlan:
    pending: list[Game]
    skipped: list[tuple[Game, str]]


def plan(db: Session, games: list[Game], params: dict) -> BatchPlan:
    pending: list[Game] = []
    skipped: list[tuple[Game, str]] = []
    for game in games:
        reason = skip_reason(db, game, params)
        if reason:
            skipped.append((game, reason))
        else:
            pending.append(game)
    return BatchPlan(pending, skipped)


def create(db: Session, owner_id: uuid.UUID, games: list[Game], params: dict) -> AnalysisBatch:
    s = get_settings()
    if running_batch(db, owner_id) is not None:
        raise BatchError(409, "You already have a batch running. Wait for it or cancel it first.")
    if not games:
        raise BatchError(422, "There are no games to analyze.")
    if len(games) > s.batch_max_games:
        raise BatchError(
            422, f"A batch can hold at most {s.batch_max_games} games; narrow the selection."
        )
    p = plan(db, games, params)
    if not p.pending:
        raise BatchError(422, "None of these games can be analyzed with these settings.")

    batch = AnalysisBatch(owner_id=owner_id, status=RUNNING, params=params)
    db.add(batch)
    db.flush()
    position = 0
    for game in p.pending:
        db.add(BatchGame(batch_id=batch.id, game_id=game.id, position=position, state="pending"))
        position += 1
    for game, reason in p.skipped:
        db.add(
            BatchGame(
                batch_id=batch.id, game_id=game.id, position=position, state="skipped", message=reason
            )
        )
        position += 1
    try:
        db.commit()
    except IntegrityError as exc:  # a concurrent request created one first
        db.rollback()
        raise BatchError(409, "You already have a batch running.") from exc
    advance(db, batch)
    return batch


def append(db: Session, batch: AnalysisBatch, games: list[Game], params: dict) -> int:
    """Add games to a running batch (they use the batch's own settings). Returns how many."""
    p = plan(db, games, params)
    existing = {i.game_id for i in items(db, batch.id)}
    last = db.scalar(select(func.max(BatchGame.position)).where(BatchGame.batch_id == batch.id))
    position = (last if last is not None else -1) + 1
    added = 0
    for game in p.pending:
        if game.id in existing:
            continue
        db.add(BatchGame(batch_id=batch.id, game_id=game.id, position=position, state="pending"))
        position += 1
        added += 1
    db.commit()
    return added


def queue_imported(db: Session, user: User, games: list[Game]) -> int:
    """The "analyze new games automatically" setting: queue freshly imported games, a limited
    number per import. They join the person's running batch if there is one. Never raises, since
    the import itself has already succeeded. Returns how many games were queued."""
    prefs = user_settings.effective(user)
    if not prefs["auto_analyze"] or not games:
        return 0
    try:
        chosen = games[: get_settings().auto_analyze_max_per_import]
        running = running_batch(db, user.id)
        if running is not None:
            added = append(db, running, chosen, running.params)
            advance(db, running)
            return added
        params = validate_params(prefs["default_depth"], None, prefs["default_multipv"])
        batch = create(db, user.id, chosen, params)
        return counts(db, batch.id)["pending"] + counts(db, batch.id)["queued"]
    except (BatchError, AnalysisRequestError):
        db.rollback()
        return 0


def items(db: Session, batch_id: uuid.UUID) -> list[BatchGame]:
    return list(
        db.scalars(
            select(BatchGame).where(BatchGame.batch_id == batch_id).order_by(BatchGame.position)
        )
    )


def counts(db: Session, batch_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(BatchGame.state, func.count())
        .where(BatchGame.batch_id == batch_id)
        .group_by(BatchGame.state)
    )
    out = {"pending": 0, "queued": 0, "done": 0, "failed": 0, "skipped": 0, "cancelled": 0}
    for state, n in rows:
        out[state] = n
    return out


def _sync_queued(db: Session, batch: AnalysisBatch) -> None:
    """Copy the outcome of finished jobs onto their batch rows."""
    queued = db.scalars(
        select(BatchGame).where(BatchGame.batch_id == batch.id, BatchGame.state == "queued")
    ).all()
    for item in queued:
        job = db.get(AnalysisJob, item.job_id) if item.job_id else None
        if job is None:
            item.state, item.message = "failed", "The analysis job no longer exists."
        elif job.status == "completed":
            item.state, item.message = "done", None
        elif job.status == "failed":
            item.state, item.message = "failed", (job.error or "The analysis failed.")[:300]
        elif job.status == "cancelled":
            item.state, item.message = "cancelled", None


def advance(db: Session, batch: AnalysisBatch) -> None:
    """Record finished games, queue more up to the feed limit, and finish the batch when done."""
    db.refresh(batch)
    if batch.status != RUNNING:
        return
    _sync_queued(db, batch)
    db.commit()

    slots = feed_limit() - counts(db, batch.id)["queued"]
    if slots > 0:
        pending = db.scalars(
            select(BatchGame)
            .where(BatchGame.batch_id == batch.id, BatchGame.state == "pending")
            .order_by(BatchGame.position)
        ).all()
        p = batch.params
        for item in pending:
            if slots <= 0:
                break
            game = db.get(Game, item.game_id)
            if game is None:
                item.state, item.message = "failed", "The game no longer exists."
                continue
            try:
                result = start_analysis(db, game, p.get("depth"), p.get("nodes"), int(p["multipv"]))
            except AnalysisRequestError as exc:
                if exc.status_code == 429:  # the person's or the server's queue is full: try later
                    break
                item.state, item.message = "failed", exc.message[:300]
                continue
            if result.job is None:
                item.state, item.message = "done", "Already analyzed with these settings."
            else:
                item.state, item.job_id = "queued", result.job.id
                slots -= 1
        db.commit()

    c = counts(db, batch.id)
    if c["pending"] == 0 and c["queued"] == 0:
        batch.status = "completed"
        batch.finished_at = utcnow()
        db.commit()


def cancel(db: Session, batch: AnalysisBatch) -> None:
    """Stop the batch: waiting games are dropped, queued jobs cancelled, and a job already
    running stops at its next position (its partial result is discarded; an existing review of
    that game is untouched)."""
    advance(db, batch)  # record anything that finished in the meantime first
    if batch.status != RUNNING:
        return
    live = db.scalars(
        select(BatchGame).where(
            BatchGame.batch_id == batch.id, BatchGame.state.in_(("pending", "queued"))
        )
    ).all()
    queue.cancel_jobs(db, [i.job_id for i in live if i.job_id])
    for item in live:
        item.state, item.message = "cancelled", None
    batch.status = "cancelled"
    batch.finished_at = utcnow()
    db.commit()


def advance_all(db: Session) -> int:
    """Called from the worker's maintenance loop. Returns how many batches were looked at."""
    ids = list(db.scalars(select(AnalysisBatch.id).where(AnalysisBatch.status == RUNNING)))
    for batch_id in ids:
        try:
            batch = db.get(AnalysisBatch, batch_id)
            if batch is not None:
                advance(db, batch)
        except Exception:
            db.rollback()
            log.exception("could not advance batch %s", batch_id)
    return len(ids)
