"""Worker process: polls the Postgres queue and runs one analysis at a time.

Scale throughput by running more worker processes (each owns exactly one Stockfish):
    docker compose up -d --scale worker=2
"""
import logging
import os
import signal
import socket
import threading

from app.config import get_settings
from app.db import SessionLocal
from app.services.analysis.engine import StockfishEngine
from worker.runner import EngineHolder, JobRunner

log = logging.getLogger("worker")


def maintenance_loop(runner: JobRunner, stop: threading.Event, interval: float) -> None:
    while not stop.wait(interval):
        try:
            runner.maintenance()
        except Exception:
            log.exception("maintenance failed")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    engines = EngineHolder(StockfishEngine)
    runner = JobRunner(SessionLocal, engines, worker_id, stop, settings)
    threading.Thread(
        target=maintenance_loop,
        args=(runner, stop, settings.maintenance_interval_seconds),
        daemon=True,
    ).start()
    log.info("worker %s started", worker_id)

    while not stop.is_set():
        try:
            ran = runner.run_once()
        except Exception:  # e.g. database not migrated yet / briefly unavailable
            log.exception("job loop error; retrying")
            ran = False
            stop.wait(2.0)
        if not ran:
            stop.wait(settings.worker_poll_seconds)

    engines.reset()
    log.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
