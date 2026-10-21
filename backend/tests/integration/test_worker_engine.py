"""Worker pipeline against the real Stockfish binary."""
import threading
import time
from pathlib import Path

import chess
import chess.engine
import pytest

from app.config import get_settings
from app.services.analysis.engine import SearchLimit, StockfishEngine
from worker.runner import EngineHolder, JobRunner

pytestmark = pytest.mark.engine
FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_full_pipeline_with_real_stockfish(client, db_factory):
    pgn = (FIXTURES / "fools_mate.pgn").read_text(encoding="utf-8")
    gid = client.post("/api/imports/pgn", json={"pgn_text": pgn}).json()["imported"][0]["id"]
    assert client.post(f"/api/games/{gid}/analysis", json={"depth": 8}).status_code == 202

    runner = JobRunner(db_factory, EngineHolder(StockfishEngine), "it", settings=get_settings())
    try:
        assert runner.run_once()
    finally:
        runner.engines.reset()

    review = client.get(f"/api/games/{gid}/analysis").json()
    assert review["run"]["engine_name"].startswith("Stockfish")
    pos = review["positions"]
    assert len(pos) == 5
    assert pos[3]["eval"]["mate"] == -1 and pos[3]["eval"]["display"] == "-#1"  # after 2.g4
    assert pos[3]["best_move_san"] == "Qh4#"
    assert pos[4]["eval"]["terminal_result"] == "0-1" and pos[4]["eval"]["cp"] is None
    assert pos[3]["classification"] == "blunder"  # 2.g4?? allows mate in one
    assert pos[4]["classification"] == "best"  # 2...Qh4#
    assert review["summary"]["complete"]


def test_killing_the_engine_unblocks_a_stuck_search():
    """The watchdog's mechanism: a search that never ends is aborted by killing Stockfish."""
    engine = StockfishEngine()
    errors: list[Exception] = []

    def endless_search() -> None:
        try:
            engine.evaluate(chess.Board(), SearchLimit(depth=60, max_seconds=None))
        except chess.engine.EngineTerminatedError as exc:
            errors.append(exc)

    t = threading.Thread(target=endless_search)
    t.start()
    time.sleep(1.0)
    assert t.is_alive()  # really stuck in the search
    engine.kill()
    t.join(15)
    assert not t.is_alive() and errors
    engine.close()  # closing an already-dead engine must not raise
