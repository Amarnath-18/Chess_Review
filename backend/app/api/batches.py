import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.config import get_settings
from app.models.analysis import AnalysisJob
from app.models.batch import AnalysisBatch
from app.models.game import Game
from app.models.user import User
from app.schemas.batches import (
    BatchEstimateOut,
    BatchItemOut,
    BatchOut,
    BatchRequest,
)
from app.services import games as games_svc
from app.services import user_settings
from app.services.analysis import batches as svc
from app.services.analysis.estimate import UNCERTAINTY, calibration, seconds_per_position

router = APIRouter(prefix="/api/analysis/batches", tags=["batches"])


def _resolve(db: Session, user: User, body: BatchRequest) -> tuple[list[Game], dict]:
    """The games a request means (owner-scoped) and its validated settings."""
    prefs = user_settings.effective(user)
    depth, nodes = body.depth, body.nodes
    if depth is None and nodes is None:
        depth = prefs["default_depth"]
    try:
        params = svc.validate_params(depth, nodes, body.multipv or prefs["default_multipv"])
    except svc.BatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if body.game_ids:
        ids = list(dict.fromkeys(body.game_ids))
        found = {
            g.id: g
            for g in db.scalars(select(Game).where(Game.owner_id == user.id, Game.id.in_(ids)))
        }
        if len(found) != len(ids):
            raise HTTPException(status_code=404, detail="Game not found")
        games = [found[i] for i in ids]
        if body.only_unanalyzed:
            games = [g for g in games if g.current_analysis_id is None]
        return games, params

    f = body.filter
    filters = games_svc.GameFilters(
        q=f.q if f else None,
        source=f.source if f else None,
        result=f.result if f else None,
        date_from=f.date_from if f else None,
        date_to=f.date_to if f else None,
        analyzed=False if body.only_unanalyzed else None,
        favorite=f.favorite if f else None,
        tag=f.tag if f else None,
    )
    stmt = (
        select(Game)
        .where(*games_svc._conditions(user.id, filters))  # noqa: SLF001
        .order_by(*games_svc._order(filters))  # noqa: SLF001
        .limit(get_settings().batch_max_games + 1)  # one more than allowed, to detect "too many"
    )
    return list(db.scalars(stmt)), params


@router.post("/estimate", response_model=BatchEstimateOut)
def estimate_batch(
    body: BatchRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """What a batch with these games and settings would involve, before starting it."""
    games, params = _resolve(db, user, body)
    s = get_settings()
    p = svc.plan(db, games, params)
    positions = sum(g.ply_count + 1 for g in p.pending)
    seconds = low = high = None
    if params["depth"] is not None and params["nodes"] is None:
        factor, used = calibration(db)
        seconds = positions * seconds_per_position(params["depth"], params["multipv"]) * factor
        low, high = seconds / UNCERTAINTY, seconds * UNCERTAINTY
    else:
        _, used = calibration(db)
    return BatchEstimateOut(
        games=len(p.pending),
        skipped=len(p.skipped),
        positions=positions,
        seconds=seconds,
        seconds_low=low,
        seconds_high=high,
        too_many=len(games) > s.batch_max_games,
        max_games=s.batch_max_games,
        calibrated_from_runs=used,
    )


def _out(db: Session, batch: AnalysisBatch) -> BatchOut:
    rows = svc.items(db, batch.id)
    games = {
        g.id: g for g in db.scalars(select(Game).where(Game.id.in_([r.game_id for r in rows])))
    }
    jobs = {
        j.id: j
        for j in db.scalars(select(AnalysisJob).where(AnalysisJob.id.in_([r.job_id for r in rows if r.job_id])))
    }
    items = []
    for r in rows:
        g = games.get(r.game_id)
        job = jobs.get(r.job_id) if r.job_id else None
        running = r.state == "queued" and job is not None and job.status == "running"
        items.append(
            BatchItemOut(
                game_id=r.game_id,
                white=g.white if g else "?",
                black=g.black if g else "?",
                state=r.state,
                message=r.message,
                progress_done=job.progress_done if running else None,
                progress_total=job.progress_total if running else None,
            )
        )
    return BatchOut(
        id=batch.id,
        status=batch.status,
        params=batch.params,
        created_at=batch.created_at,
        finished_at=batch.finished_at,
        total=len(rows),
        counts=svc.counts(db, batch.id),
        items=items,
    )


def _owned(db: Session, user: User, batch_id: uuid.UUID) -> AnalysisBatch:
    batch = db.scalar(
        select(AnalysisBatch).where(AnalysisBatch.id == batch_id, AnalysisBatch.owner_id == user.id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(
    body: BatchRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    games, params = _resolve(db, user, body)
    try:
        batch = svc.create(db, user.id, games, params)
    except svc.BatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _out(db, batch)


@router.get("/latest", response_model=BatchOut | None)
def latest_batch(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The running batch, or else the most recent one; null if there never was one."""
    batch = svc.running_batch(db, user.id) or db.scalar(
        select(AnalysisBatch)
        .where(AnalysisBatch.owner_id == user.id)
        .order_by(AnalysisBatch.created_at.desc())
        .limit(1)
    )
    return _out(db, batch) if batch else None


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _out(db, _owned(db, user, batch_id))


@router.post("/{batch_id}/cancel", response_model=BatchOut)
def cancel_batch(
    batch_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    batch = _owned(db, user, batch_id)
    svc.cancel(db, batch)
    return _out(db, batch)
