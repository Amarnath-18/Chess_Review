import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.config import get_settings
from app.models.analysis import AnalysisJob, AnalysisPosition, AnalysisRun
from app.models.user import User
from app.schemas.analysis import (
    AltLineOut,
    AnalysisOut,
    AnalysisRequest,
    AnalysisStartOut,
    EstimateOut,
    EvalOut,
    JobOut,
    LineOut,
    PartialAnalysisOut,
    PositionOut,
    RunOut,
)
from app.services import games as games_svc
from app.services import user_settings
from app.services.analysis.engine import SearchLimit
from app.services.analysis.estimate import estimate as estimate_run
from app.services.analysis.service import AnalysisRequestError, start_analysis
from app.services.analysis.store import pv_to_san, to_san
from app.services.analysis.store import row_to_position
from app.services.classification.accuracy import game_accuracy
from app.services.classification.classify import classify_move
from app.services.classification.config import ClassificationConfig
from app.services.classification.score import Score, win_pct_white
from app.services.openings import book_run

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
    prefs = user_settings.effective(user)
    depth = body.depth
    if depth is None and body.nodes is None:  # nothing chosen: the user's own default depth
        depth = prefs["default_depth"]
    multipv = body.multipv or prefs["default_multipv"]
    return _start(db, game, depth, body.nodes, multipv, response)


@router.get("/games/{game_id}/analysis/estimate", response_model=EstimateOut)
def estimate_analysis(
    game_id: uuid.UUID,
    depth: int | None = Query(None, ge=1),
    nodes: int | None = Query(None, ge=1),
    multipv: int | None = Query(None, ge=1),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Roughly how long analysing this game with these settings would take (omitted settings
    default to the user's own, exactly as when starting the analysis)."""
    game = _owned_game(db, user, game_id)
    prefs = user_settings.effective(user)
    if depth is None and nodes is None:
        depth = prefs["default_depth"]
    lines = multipv or prefs["default_multipv"]
    try:
        SearchLimit(depth=depth, nodes=nodes).validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not 1 <= lines <= get_settings().max_multipv:
        raise HTTPException(
            status_code=422,
            detail=f"Engine lines must be between 1 and {get_settings().max_multipv}.",
        )
    return EstimateOut(**vars(estimate_run(db, game, depth, nodes, lines)))


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


def _apply_book(rows: list[AnalysisPosition], positions: list[PositionOut], summary: dict) -> dict:
    """Mark opening-book moves (a quiet mark that replaces Best/Excellent/Good/Inaccuracy; Brilliant,
    Great, Mistake and Blunder are never hidden), keep the summary consistent, and name the opening."""
    if not rows:
        return summary
    hits = book_run(rows[0].fen, [r.fen for r in rows[1:]])
    counts = summary.get("counts")
    book_plies: set[int] = set()
    deepest: tuple[int, tuple[str, str]] | None = None
    for ply, hit in enumerate(hits, start=1):
        if hit is None:
            continue
        deepest = (ply, hit)
        pos = positions[ply]
        pos.opening = hit[1]
        if pos.classification is None or pos.classification in (
            "brilliant", "great", "mistake", "blunder"
        ):
            continue  # a real loss stays visible even when the line is in the dataset
        if counts:
            side = "white" if rows[ply - 1].fen.split()[1] == "w" else "black"
            counts[side][pos.classification] -= 1
            counts[side]["book"] = counts[side].get("book", 0) + 1
        pos.classification = "book"
        book_plies.add(ply)
    if counts:
        for side in ("white", "black"):
            counts[side].setdefault("book", 0)
    summary["key_positions"] = [
        k for k in summary.get("key_positions", []) if k["ply"] not in book_plies
    ]
    summary["opening"] = (
        {"eco": deepest[1][0], "name": deepest[1][1], "ply": deepest[0]} if deepest else None
    )
    return summary


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


def _run_out(run: AnalysisRun) -> RunOut:
    return RunOut(
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
    )


def _accuracy(rows: list[AnalysisPosition]) -> dict:
    """Per-side accuracy from the saved evaluations (computed on read, so older reviews get it too)."""
    wins: list[float | None] = []
    for r in rows:
        s = _score(r.score_cp, r.score_mate, r.terminal_result)
        wins.append(win_pct_white(s) if s is not None else None)
    losses = [r.loss_pct for r in rows[1:]]
    movers = [rows[i].fen.split()[1] == "w" for i in range(len(rows) - 1)]
    return game_accuracy(wins, losses, movers)


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
    positions = [_position_out(r) for r in rows]
    summary = _apply_book(
        list(rows), positions, {**(run.summary or {}), "accuracy": _accuracy(list(rows))}
    )
    return AnalysisOut(
        run=_run_out(run),
        summary=summary,
        positions=positions,
    )


@router.get("/games/{game_id}/analysis/partial", response_model=PartialAnalysisOut)
def get_partial_analysis(
    game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """A live preview of the analysis that is running right now: the positions evaluated so far,
    classified on the fly. It is never the saved review, so it carries no summary or accuracy,
    and it disappears (404) as soon as the job is no longer running."""
    game = _owned_game(db, user, game_id)
    job = db.scalars(
        select(AnalysisJob)
        .where(
            AnalysisJob.game_id == game.id,
            AnalysisJob.status == "running",
            AnalysisJob.run_id.is_not(None),
        )
        .order_by(AnalysisJob.created_at.desc())
    ).first()
    run = db.get(AnalysisRun, job.run_id) if job else None
    if job is None or run is None or run.status != "running":
        raise HTTPException(status_code=404, detail="No analysis is running for this game.")
    rows = list(
        db.scalars(
            select(AnalysisPosition)
            .where(AnalysisPosition.run_id == run.id)
            .order_by(AnalysisPosition.ply)
        )
    )
    config = ClassificationConfig()
    evals = [row_to_position(r) for r in rows]
    positions = [_position_out(r) for r in rows]
    for i in range(1, len(rows)):
        if rows[i].ply != rows[i - 1].ply + 1 or not rows[i].played_move_uci:
            continue  # evaluated out of order: no classification until both neighbours exist
        result = classify_move(evals[i - 1], evals[i], rows[i].played_move_uci, config)
        if result is not None:
            p = positions[i]
            p.classification = result.classification.value
            p.loss_pct = round(result.loss, 2)
            p.missed_win = result.missed_win
            p.is_sacrifice = result.is_sacrifice
    _apply_book(rows, positions, {})
    return PartialAnalysisOut(
        run=_run_out(run),
        done=job.progress_done,
        total=job.progress_total,
        positions=positions,
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
