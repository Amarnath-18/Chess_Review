"""Executes analysis jobs. One engine, one job at a time per worker process."""
from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

import chess.engine
import chess.pgn
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.models.analysis import AnalysisJob, AnalysisRun
from app.models.base import utcnow
from app.models.game import Game
from app.services.analysis.engine import SearchLimit
from app.services.analysis.estimate import job_time_limit
from app.services.analysis.runner import Evaluator, evaluate_game, replay
from app.services.analysis.store import (
    fail_run,
    find_completed_run,
    make_cache_key,
    position_row,
    write_classifications,
)
from app.services.classification.classify import PositionEval, classify_game
from app.services.classification.config import ClassificationConfig
from app.services.classification.summary import summarize
from app.services.jobs import queue
from app.services.jobs.queue import LostJob
from app.services.retention import PurgeResult, purge_inactive

log = logging.getLogger("worker")


class JobInterrupted(Exception):
    """The worker is shutting down; the job goes back to the queue."""


class JobTimeout(Exception):
    pass


class AnalysisIncomplete(Exception):
    pass


class RunnableEngine(Evaluator, Protocol):
    def kill(self) -> None: ...
    def close(self) -> None: ...


class EngineHolder:
    """Creates the engine lazily and rebuilds it after a crash."""

    def __init__(self, factory: Callable[[], RunnableEngine]) -> None:
        self._factory = factory
        self._engine: RunnableEngine | None = None

    def get(self) -> RunnableEngine:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine

    def reset(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.close()
            except Exception:  # the process may already be dead
                log.debug("engine close failed", exc_info=True)


class JobRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        engines: EngineHolder,
        worker_id: str,
        stop: threading.Event | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.engines = engines
        self.worker_id = worker_id
        self.stop = stop or threading.Event()
        self.settings = settings or get_settings()
        # Shared with the maintenance thread (watchdog):
        self._active_engine: RunnableEngine | None = None
        self._last_purge: float | None = None
        self._last_progress = time.monotonic()

    # ---- public API ---------------------------------------------------------

    def run_once(self) -> bool:
        """Claim and process one job. Returns False if the queue was empty."""
        with self.session_factory() as db:
            job = queue.claim_next(db, self.worker_id)
            if job is None:
                return False
            job_id = job.id
        self._process(job_id)
        return True

    def maintenance(self) -> None:
        """Called periodically from another thread: reap dead jobs, kill hung engines, and
        (hourly) delete data nobody has visited within the retention period."""
        with self.session_factory() as db:
            reaped = queue.reap_stale(db, self.settings.job_stale_seconds)
            if reaped:
                log.warning("reaped stale jobs: %s", reaped)
        self._maybe_purge()
        self.check_hung()

    def _maybe_purge(self) -> PurgeResult | None:
        now = time.monotonic()
        if (
            self._last_purge is not None
            and now - self._last_purge < self.settings.retention_purge_interval_seconds
        ):
            return None
        self._last_purge = now
        with self.session_factory() as db:
            result = purge_inactive(db, self.settings.retention_days)
        if result.users or result.expired_sessions:
            log.info(
                "retention purge: %d inactive user(s), %d game(s), %d expired session(s)",
                result.users,
                result.games,
                result.expired_sessions,
            )
        return result

    def check_hung(self) -> bool:
        engine = self._active_engine
        if engine is None:
            return False
        limit = self.settings.max_seconds_per_position + self.settings.engine_hang_grace_seconds
        if time.monotonic() - self._last_progress > limit:
            log.error("engine made no progress for %.0fs; killing it", limit)
            engine.kill()
            self._last_progress = time.monotonic()
            return True
        return False

    # ---- job execution ------------------------------------------------------

    def _process(self, job_id) -> None:
        with self.session_factory() as db:
            job = db.get(AnalysisJob, job_id)
            if job is None:  # its game or user was deleted between claiming and starting
                return
            # Plain values: the job row can be deleted under us (see _abort), and reading an
            # attribute of a deleted row would raise.
            attempts, max_attempts = job.attempts, job.max_attempts
            wid = self.worker_id
            run_id = None
            try:
                run_id = self._execute(db, job)
            except JobInterrupted:
                self._abort(
                    db,
                    job_id,
                    "interrupted by worker shutdown",
                    lambda: queue.requeue(db, job_id, wid, consume_attempt=False),
                )
            except LostJob:
                log.warning("job %s was taken over by the reaper; abandoning it", job_id)
                self._abort(db, job_id, "job was reassigned")
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
                self.engines.reset()
                log.exception("engine failure on job %s", job_id)
                if attempts < max_attempts:
                    action = lambda: queue.requeue(db, job_id, wid)  # noqa: E731
                else:
                    msg = f"The analysis engine failed: {exc}"
                    action = lambda: queue.fail(db, job_id, wid, msg)  # noqa: E731
                self._abort(db, job_id, f"engine failure: {exc}", action)
            except (JobTimeout, AnalysisIncomplete, ValueError) as exc:
                reason = str(exc)  # `exc` itself is unbound once this block ends
                self._abort(db, job_id, reason, lambda: queue.fail(db, job_id, wid, reason))
            except Exception as exc:
                db.rollback()
                if self._job_gone(db, job_id):
                    log.info("job %s was deleted while it ran (its game was removed)", job_id)
                else:
                    log.exception("unexpected error on job %s", job_id)
                msg = "Internal error while analyzing the game."
                self._abort(
                    db, job_id, f"internal error: {exc}", lambda: queue.fail(db, job_id, wid, msg)
                )
            finally:
                self._active_engine = None
            log.info("job %s finished (run %s)", job_id, run_id)

    @staticmethod
    def _job_gone(db: Session, job_id) -> bool:
        stmt = select(func.count()).select_from(AnalysisJob).where(AnalysisJob.id == job_id)
        return db.scalar(stmt) == 0

    def _abort(self, db: Session, job_id, reason: str, action=None) -> None:
        """Undo this attempt: roll back, drop the partial run, then apply `action` (requeue or
        fail). Never raises: deleting a game or a user removes the job and run rows themselves,
        and then there is simply nothing left to clean up."""
        try:
            db.rollback()
            run_id = db.scalar(select(AnalysisJob.run_id).where(AnalysisJob.id == job_id))
            if run_id is not None:
                fail_run(db, run_id, reason)
            if action is not None:
                action()
            db.commit()
        except Exception:
            db.rollback()
            log.warning("could not clean up job %s (probably deleted)", job_id, exc_info=True)

    def _execute(self, db: Session, job: AnalysisJob):
        s = self.settings
        game = db.get(Game, job.game_id)
        if game is None:
            raise ValueError("The game no longer exists.")
        engine = self.engines.get()
        self._active_engine = engine
        self._last_progress = time.monotonic()

        params = job.params
        limit = SearchLimit(
            depth=params.get("depth"),
            nodes=params.get("nodes"),
            max_seconds=s.max_seconds_per_position,
        ).validate(s)
        multipv = int(params.get("multipv", 2))
        config = ClassificationConfig()
        key = make_cache_key(engine.name, limit, multipv, config.config_hash())

        # Another job may have produced this exact review while we waited in the queue.
        cached = find_completed_run(db, game.id, key)
        if cached is not None:
            game.current_analysis_id = cached.id
            queue.complete(db, job.id, self.worker_id, cached.id)
            db.commit()
            return cached.id

        pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
        if pgn_game is None:
            raise ValueError("The stored game could not be read.")
        _, moves, sans = replay(pgn_game)
        total = len(moves) + 1

        run = AnalysisRun(
            game_id=game.id,
            status="running",
            engine_name=engine.name,
            limit_depth=limit.depth,
            limit_nodes=limit.nodes,
            multipv=multipv,
            class_config=config.to_dict(),
            class_config_hash=config.config_hash(),
            cache_key=key,
        )
        db.add(run)
        db.flush()
        queue.set_run(db, job.id, self.worker_id, run.id, total)
        db.commit()
        run_id = run.id

        limit_s = job_time_limit(total, s)
        deadline = time.monotonic() + limit_s

        def on_position(ply: int, pos: PositionEval, _total: int) -> None:
            self._last_progress = time.monotonic()
            if self.stop.is_set():
                raise JobInterrupted()
            if time.monotonic() > deadline:
                raise JobTimeout(
                    f"The analysis exceeded its {limit_s:.0f}s time limit. "
                    "Try a lower depth or fewer lines."
                )
            uci = moves[ply - 1].uci() if ply > 0 else None
            san = sans[ply - 1] if ply > 0 else None
            db.add(position_row(run_id, ply, pos, uci, san))
            queue.heartbeat(db, job.id, self.worker_id, done=ply + 1)
            db.commit()  # incremental, but invisible until the run is promoted

        positions, moves_uci, _ = evaluate_game(
            pgn_game, engine, limit, multipv, on_position=on_position
        )

        missing = [i for i, p in enumerate(positions) if p.score is None]
        if missing:
            raise AnalysisIncomplete(
                f"{len(missing)} position(s) could not be evaluated, so no review was saved."
            )

        results = classify_game(positions, moves_uci, config)
        summary = summarize(positions, results, config, complete=True)

        # Promote atomically: classifications + completed run + pointer swap + job done.
        write_classifications(db, run_id, results)
        run = db.get(AnalysisRun, run_id)
        assert run is not None
        run.status = "completed"
        run.summary = summary
        run.finished_at = utcnow()
        game = db.get(Game, job.game_id)
        assert game is not None
        game.current_analysis_id = run_id
        queue.complete(db, job.id, self.worker_id, run_id)
        db.commit()
        return run_id
