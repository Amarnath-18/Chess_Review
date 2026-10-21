import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.analysis import AnalysisJob, AnalysisPosition, AnalysisRun
from app.models.user import User
from app.schemas.analysis import (
    AltLineOut,
    AnalysisOut,
    AnalysisRequest,
    AnalysisStartOut,
    EvalOut,
    JobOut,
    LineOut,
    PositionOut,
    RunOut,
)
from app.services import games as games_svc
from app.services.analysis.service import AnalysisRequestError, start_analysis
from app.services.analysis.store import pv_to_san, to_san
from app.services.classification.score import Score, win_pct_white

router = APIRouter(prefix="/api", tags=["analysis"])


def _owned_game(db: Session, user: User, game_id: uuid.UUID):
    game = games_svc.get_owned_game(db, user.id, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _owned_job(db: Session, user: User, job_id: uuid.UUID) -> AnalysisJob:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.owner_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _start(db: Session, game, depth, nodes, multipv, response: Response) -> AnalysisStartOut:
    try:
        result = start_analysis(db, game, depth, nodes, multipv)
    except AnalysisRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if result.job is None:
        response.status_code = 200
        return AnalysisStartOut(cached=True, job=None, run_id=result.run.id if result.run else None)
    response.status_code = 202
    return AnalysisStartOut(cached=False, job=JobOut.model_validate(result.job), run_id=None)


@router.post("/games/{game_id}/analysis", response_model=AnalysisStartOut, status_code=202)
def request_analysis(
    game_id: uuid.UUID,
    response: Response,
    body: AnalysisRequest | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Queue an analysis, or reuse a completed review made with identical settings (200)."""
    body = body or AnalysisRequest()
    game = _owned_game(db, user, game_id)
    return _start(db, game, body.depth, body.nodes, body.multipv, response)


def _eval_out(score: Score | None, cols: tuple) -> EvalOut:
    cp, mate, terminal = cols
    return EvalOut(
        cp=cp,
        mate=mate,
        terminal_result=terminal,
        display=score.display() if score else None,
        win_pct=round(win_pct_white(score), 2) if score else None,
    )


def _score(cp, mate, terminal) -> Score | None:
    if cp is None and mate is None and terminal is None:
        return None
    return Score(cp=cp, mate=mate, final=terminal)


def _lines_out(row: AnalysisPosition) -> list[LineOut]:
    """All stored engine lines; reviews made before multi-line support fall back to lines 1-2."""
    raw: list[tuple[int | None, int | None, list[str]]] = []
    if row.lines:
        raw = [(ln.get("cp"), ln.get("mate"), ln.get("pv") or []) for ln in row.lines]
    elif row.pv_uci is not None and row.terminal_result is None:
        raw.append((row.score_cp, row.score_mate, row.pv_uci))
        if row.alt_score_cp is not None or row.alt_score_mate is not None:
            raw.append((row.alt_score_cp, row.alt_score_mate, row.alt_pv_uci or []))
    out = []
    for rank, (cp, mate, pv) in enumerate(raw, start=1):
        score = _score(cp, mate, None)
        if score is None:
            continue
        first = pv[0] if pv else None
        out.append(
            LineOut(
                rank=rank,
                move_uci=first,
                move_san=to_san(row.fen, first),
                eval=_eval_out(score, (cp, mate, None)),
                pv_san=pv_to_san(row.fen, pv),
            )
        )
    return out


def _position_out(row: AnalysisPosition) -> PositionOut:
    score = _score(row.score_cp, row.score_mate, row.terminal_result)
    best_uci = row.pv_uci[0] if row.pv_uci else None
    lines = _lines_out(row)
    alt = None
    if len(lines) > 1:
        alt = AltLineOut(move_uci=lines[1].move_uci, move_san=lines[1].move_san, eval=lines[1].eval)
    return PositionOut(
        ply=row.ply,
        fen=row.fen,
        eval=_eval_out(score, (row.score_cp, row.score_mate, row.terminal_result)),
        depth=row.depth_reached,
        best_move_uci=best_uci,
        best_move_san=to_san(row.fen, best_uci),
        pv_san=pv_to_san(row.fen, row.pv_uci),
        lines=lines,
        alt=alt,
        played_move_uci=row.played_move_uci,
        played_move_san=row.played_move_san,
        classification=row.classification,
        loss_pct=round(row.loss_pct, 2) if row.loss_pct is not None else None,
        missed_win=row.missed_win,
        is_sacrifice=row.is_sacrifice,
    )


@router.get("/games/{game_id}/analysis", response_model=AnalysisOut)
def get_analysis(
    game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """The game's current completed review. Partial or failed runs are never returned."""
    game = _owned_game(db, user, game_id)
    run = db.get(AnalysisRun, game.current_analysis_id) if game.current_analysis_id else None
    if run is None or run.status != "completed":
        raise HTTPException(status_code=404, detail="This game has not been analyzed yet.")
    rows = db.scalars(
        select(AnalysisPosition)
        .where(AnalysisPosition.run_id == run.id)
        .order_by(AnalysisPosition.ply)
    ).all()
    return AnalysisOut(
        run=RunOut(
            id=run.id,
            status=run.status,
            engine_name=run.engine_name,
            depth=run.limit_depth,
            nodes=run.limit_nodes,
            multipv=run.multipv,
            class_config_hash=run.class_config_hash,
            class_config=run.class_config,
            started_at=run.started_at,
            finished_at=run.finished_at,
        ),
        summary=run.summary or {},
        positions=[_position_out(r) for r in rows],
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return JobOut.model_validate(_owned_job(db, user, job_id))


@router.post("/jobs/{job_id}/retry", response_model=AnalysisStartOut, status_code=202)
def retry_job(
    job_id: uuid.UUID,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Retry a failed job with its original settings. Safe to repeat: it never touches the
    game's existing review until a new run completes."""
    job = _owned_job(db, user, job_id)
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried.")
    game = games_svc.get_owned_game(db, user.id, job.game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    p = job.params
    return _start(db, game, p.get("depth"), p.get("nodes"), int(p.get("multipv", 3)), response)
