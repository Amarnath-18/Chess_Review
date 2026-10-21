"""Postgres-backed job queue. Callers own the transaction unless a function says it commits."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisJob
from app.models.base import utcnow
from app.services.analysis.store import fail_run

ACTIVE = ("queued", "running")


class LostJob(Exception):
    """This worker no longer owns the job (it was reaped / requeued meanwhile)."""


def claim_next(db: Session, worker_id: str) -> AnalysisJob | None:
    """Atomically take the oldest queued job. Commits."""
    job = db.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.status == "queued")
        .order_by(AnalysisJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.rollback()
        return None
    now = utcnow()
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.heartbeat_at = now
    job.started_at = now
    job.finished_at = None
    job.error = None
    job.progress_done = 0
    job.run_id = None
    db.commit()
    return job


def _owned(job_id: uuid.UUID, worker_id: str):
    return (
        AnalysisJob.id == job_id,
        AnalysisJob.status == "running",
        AnalysisJob.locked_by == worker_id,
    )


def _require(result) -> None:
    if result.rowcount != 1:
        raise LostJob()


def set_run(db: Session, job_id: uuid.UUID, worker_id: str, run_id: uuid.UUID, total: int) -> None:
    _require(
        db.execute(
            update(AnalysisJob)
            .where(*_owned(job_id, worker_id))
            .values(run_id=run_id, progress_total=total, heartbeat_at=utcnow())
        )
    )


def heartbeat(db: Session, job_id: uuid.UUID, worker_id: str, done: int | None = None) -> None:
    values: dict = {"heartbeat_at": utcnow()}
    if done is not None:
        values["progress_done"] = done
    _require(db.execute(update(AnalysisJob).where(*_owned(job_id, worker_id)).values(**values)))


def complete(db: Session, job_id: uuid.UUID, worker_id: str, run_id: uuid.UUID) -> None:
    _require(
        db.execute(
            update(AnalysisJob)
            .where(*_owned(job_id, worker_id))
            .values(status="completed", run_id=run_id, finished_at=utcnow(), error=None)
        )
    )


def fail(db: Session, job_id: uuid.UUID, worker_id: str, error: str) -> None:
    """Mark a job failed (guarded: does nothing if another actor already changed it)."""
    db.execute(
        update(AnalysisJob)
        .where(*_owned(job_id, worker_id))
        .values(status="failed", error=error[:2000], finished_at=utcnow())
    )


def requeue(
    db: Session, job_id: uuid.UUID, worker_id: str, consume_attempt: bool = True
) -> None:
    values: dict = {"status": "queued", "locked_by": None, "heartbeat_at": None}
    if not consume_attempt:
        values["attempts"] = AnalysisJob.attempts - 1
    db.execute(update(AnalysisJob).where(*_owned(job_id, worker_id)).values(**values))


def reap_stale(db: Session, stale_seconds: int, now: datetime | None = None) -> list[uuid.UUID]:
    """Requeue (or fail, once attempts are used up) running jobs whose worker stopped
    heartbeating. Their partial runs are discarded. Commits."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=stale_seconds)
    stale = db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.status == "running", AnalysisJob.heartbeat_at < cutoff)
        .with_for_update(skip_locked=True)
    ).all()
    reaped = []
    for job in stale:
        if job.run_id is not None:
            fail_run(db, job.run_id, "worker stopped responding")
        if job.attempts < job.max_attempts:
            job.status = "queued"
        else:
            job.status = "failed"
            job.error = "The analysis worker stopped responding and retries were exhausted."
            job.finished_at = now
        job.locked_by = None
        job.heartbeat_at = None
        reaped.append(job.id)
    db.commit()
    return reaped


def active_jobs_for_user(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AnalysisJob)
            .where(AnalysisJob.owner_id == user_id, AnalysisJob.status.in_(ACTIVE))
        )
        or 0
    )


def queued_total(db: Session) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "queued")
        )
        or 0
    )


def active_job_for_game(db: Session, game_id: uuid.UUID) -> AnalysisJob | None:
    return db.scalar(
        select(AnalysisJob).where(AnalysisJob.game_id == game_id, AnalysisJob.status.in_(ACTIVE))
    )
