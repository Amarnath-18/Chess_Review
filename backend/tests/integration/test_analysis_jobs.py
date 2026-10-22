"""Job queue, worker and analysis API, driven by a deterministic fake engine.

Covers AT-10 (persistence), AT-11 (interrupted/failed jobs), AT-13 (limits) and the
FRD guarantees that a failed re-analysis never damages an existing review.
"""
import threading
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.models.analysis import AnalysisJob, AnalysisPosition, AnalysisRun
from app.models.base import utcnow
from app.models.game import Game
from app.services.jobs import queue
from tests.helpers import TERMINATED, FakeEngine
from worker.runner import EngineHolder, JobRunner

GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""


@pytest.fixture(autouse=True)
def fake_engine_name(monkeypatch):
    monkeypatch.setattr("app.services.analysis.service.get_engine_name", lambda: FakeEngine.name)


def make_game(client, white="Alice") -> str:
    r = client.post("/api/imports/pgn", json={"pgn_text": GAME.replace("Alice", white)})
    return r.json()["imported"][0]["id"]


def runner_for(db_factory, engine, stop=None, **overrides) -> JobRunner:
    settings = get_settings().model_copy(update=overrides)
    return JobRunner(db_factory, EngineHolder(lambda: engine), "test-worker", stop, settings)


def request(client, gid, **body):
    return client.post(f"/api/games/{gid}/analysis", json=body)


def scalar(db_factory, stmt):
    with db_factory() as db:
        return db.scalar(stmt)


def count(db_factory, model, *where):
    return scalar(db_factory, select(func.count()).select_from(model).where(*where))


def analyze(client, db_factory, gid, engine=None, **body):
    """Queue a job and run it to completion/failure with a fresh runner. Returns the job."""
    r = request(client, gid, **body)
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]["id"]
    assert runner_for(db_factory, engine or FakeEngine()).run_once()
    return client.get(f"/api/jobs/{job_id}").json()


# ---- requesting analysis -------------------------------------------------------------


def test_request_validation(client, monkeypatch):
    gid = make_game(client)
    assert request(client, gid, depth=999).status_code == 422  # above server cap
    assert request(client, gid, nodes=10**12).status_code == 422
    assert request(client, gid, depth=0).status_code == 422
    assert request(client, gid, multipv=0).status_code == 422  # at least one line
    r = request(client, gid, multipv=get_settings().max_multipv + 1)  # more than the server allows
    assert r.status_code == 422 and "between 1 and" in r.json()["detail"]
    assert request(client, "00000000-0000-0000-0000-000000000000").status_code == 404
    monkeypatch.setattr(get_settings(), "max_plies", 2)  # the sample game has 6 plies
    r = request(client, gid)
    assert r.status_code == 422 and "limit" in r.json()["detail"]


def test_queued_job_is_visible_and_idempotent(client):
    gid = make_game(client)
    r = request(client, gid)
    assert r.status_code == 202
    job = r.json()["job"]
    assert job["status"] == "queued" and job["params"]["depth"] == get_settings().default_depth
    assert job["progress_total"] == 7  # 6 plies + start position

    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "queued"
    assert client.get(f"/api/games/{gid}").json()["analysis_status"] == "queued"
    assert client.get("/api/games").json()["items"][0]["analysis_status"] == "queued"
    assert client.get(f"/api/games/{gid}/analysis").status_code == 404  # nothing to show yet

    again = request(client, gid)  # same settings: same job
    assert again.status_code == 202 and again.json()["job"]["id"] == job["id"]
    assert request(client, gid, depth=10).status_code == 409  # different settings: refused


def test_user_and_queue_limits(make_client, monkeypatch):
    a, b = make_client(), make_client()
    games = [make_game(a, f"P{i}") for i in range(3)]
    assert request(a, games[0]).status_code == 202
    assert request(a, games[1]).status_code == 202
    r = request(a, games[2])
    assert r.status_code == 429 and "at most 2" in r.json()["detail"]

    monkeypatch.setattr(get_settings(), "max_queue_length", 2)  # two jobs are already queued
    r = request(b, make_game(b))
    assert r.status_code == 429 and "queue is full" in r.json()["detail"]


def test_database_allows_only_one_active_job_per_game(client, db_factory):
    gid = make_game(client)
    request(client, gid)
    with db_factory() as db:
        game = db.get(Game, gid)
        db.add(AnalysisJob(game_id=game.id, owner_id=game.owner_id, status="queued", params={}))
        with pytest.raises(IntegrityError):
            db.commit()


# ---- running a job ---------------------------------------------------------------------


def test_worker_completes_a_job_and_the_review_is_served(client, db_factory):
    gid = make_game(client)
    job = analyze(client, db_factory, gid)
    assert job["status"] == "completed" and job["progress_done"] == job["progress_total"] == 7
    assert job["run_id"] and job["error"] is None

    game = client.get(f"/api/games/{gid}").json()
    assert game["analysis_status"] == "completed" and game["has_analysis"]
    assert game["latest_job"]["status"] == "completed"

    review = client.get(f"/api/games/{gid}/analysis").json()
    assert review["run"]["engine_name"] == "FakeFish 1.0" and review["run"]["status"] == "completed"
    pos = review["positions"]
    assert [p["ply"] for p in pos] == list(range(7))
    assert pos[0]["played_move_san"] is None and pos[0]["classification"] is None
    assert pos[1]["played_move_san"] == "e4"
    assert all(p["classification"] is not None for p in pos[1:])
    assert pos[0]["eval"]["display"] == "+0.30" and pos[0]["eval"]["cp"] == 30
    assert pos[0]["best_move_san"] and pos[0]["alt"]["eval"]["cp"] == -200
    summary = review["summary"]
    assert summary["complete"] and summary["analyzed_moves"] == 6
    counted = sum(sum(side.values()) for side in summary["counts"].values())
    assert counted == 6  # summary counts match the saved classifications
    acc = summary["accuracy"]
    assert all(acc[s] is not None and 0 <= acc[s] <= 100 for s in ("white", "black"))


def test_partial_preview_while_running_is_never_the_saved_review(client, db_factory, monkeypatch):
    gid = make_game(client)
    assert client.get(f"/api/games/{gid}/analysis/partial").status_code == 404  # nothing running
    assert request(client, gid).status_code == 202

    seen = {}
    real_heartbeat = queue.heartbeat

    def spy(db, job_id, worker_id, done=None, **kw):
        if done == 4:  # three positions are saved; the fourth is still being written
            seen["partial"] = client.get(f"/api/games/{gid}/analysis/partial")
            seen["review"] = client.get(f"/api/games/{gid}/analysis")
        return real_heartbeat(db, job_id, worker_id, done=done, **kw)

    monkeypatch.setattr(queue, "heartbeat", spy)
    assert runner_for(db_factory, FakeEngine()).run_once()

    assert seen["review"].status_code == 404  # incomplete work is never presented as the review
    body = seen["partial"].json()
    assert body["run"]["status"] == "running" and body["total"] == 7
    assert [p["ply"] for p in body["positions"]] == [0, 1, 2]
    assert "summary" not in body
    assert body["positions"][1]["classification"] is not None  # classified on the fly
    assert body["positions"][0]["classification"] is None

    # once finished, the preview is gone and the real review is served
    assert client.get(f"/api/games/{gid}/analysis/partial").status_code == 404
    assert client.get(f"/api/games/{gid}/analysis").status_code == 200


def test_annotated_pgn_carries_evals_and_marks_and_reimports_as_the_same_game(client, db_factory):
    import io

    import chess.pgn

    gid = make_game(client)
    plain = client.get(f"/api/games/{gid}/pgn?annotated=true")
    assert plain.status_code == 409  # not analyzed yet: no pretending

    analyze(client, db_factory, gid)
    r = client.get(f"/api/games/{gid}/pgn?annotated=true")
    assert r.status_code == 200 and "analysis.pgn" in r.headers["content-disposition"]
    game = chess.pgn.read_game(io.StringIO(r.text))
    assert not game.errors
    assert "Chess Review Lab (FakeFish" in game.headers["Annotator"]
    nodes = list(game.mainline())
    assert [n.san() for n in nodes] == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]
    review = client.get(f"/api/games/{gid}/analysis").json()
    for node, pos in zip(nodes, review["positions"][1:]):
        ev = node.eval()
        assert ev is not None, "every move carries [%eval ...]"
        assert (ev.white().score(mate_score=100000) is not None)
    # a mistake or blunder is marked with the standard symbols and says what was better
    errors = [p for p in review["positions"] if p["classification"] in ("mistake", "blunder")]
    for p in errors:
        node = nodes[p["ply"] - 1]
        assert node.nags & {chess.pgn.NAG_MISTAKE, chess.pgn.NAG_BLUNDER}
        assert "Best was" in node.comment

    # importing the annotated file again finds the same game, not a new one
    again = client.post("/api/imports/pgn", json={"pgn_text": r.text}).json()
    assert len(again["duplicates"]) == 1 and not again["imported"]

    # bulk export: analyzed games annotated, unanalyzed ones plain
    other = make_game(client, white="Zed")
    bulk = client.get("/api/games/export?annotated=true")
    assert bulk.status_code == 200 and bulk.text.count("[Annotator") == 1
    assert bulk.text.count("[Event") == 2 and "annotated" in bulk.headers["content-disposition"]
    assert other


def test_partial_preview_belongs_to_its_owner(client, make_client, db_factory):
    gid = make_game(client)
    other = make_client()
    assert other.get(f"/api/games/{gid}/analysis/partial").status_code == 404


def test_opening_book_moves_are_marked_and_summary_stays_consistent(client, db_factory):
    gid = make_game(client)
    analyze(client, db_factory, gid)
    review = client.get(f"/api/games/{gid}/analysis").json()
    pos = review["positions"]
    summary = review["summary"]

    assert summary["opening"]["eco"].startswith("C5") and "Italian" in summary["opening"]["name"]
    assert summary["opening"]["ply"] == 6  # 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 is all theory
    booked = [p for p in pos[1:] if p["classification"] == "book"]
    assert booked and all(p["opening"] for p in pos[1:])
    # a real loss is never hidden behind "book", and the counts agree with the marks
    assert not any(p["classification"] == "book" and (p["loss_pct"] or 0) >= 20 for p in pos)
    for side, parity in (("white", 1), ("black", 0)):
        marks = [p["classification"] for p in pos[1:] if p["ply"] % 2 == parity]
        for cls, n in summary["counts"][side].items():
            assert n == marks.count(cls)


def test_every_requested_engine_line_is_stored_and_served(client, db_factory):
    gid = make_game(client)
    job = analyze(client, db_factory, gid, multipv=4)
    assert job["status"] == "completed" and job["params"]["multipv"] == 4

    review = client.get(f"/api/games/{gid}/analysis").json()
    assert review["run"]["multipv"] == 4
    start = review["positions"][0]
    assert [ln["rank"] for ln in start["lines"]] == [1, 2, 3, 4]
    evals = [ln["eval"]["cp"] for ln in start["lines"]]
    assert evals == sorted(evals, reverse=True) and evals[0] == 30  # best first
    assert all(ln["move_san"] and ln["pv_san"][0] == ln["move_san"] for ln in start["lines"])
    # the older single-line fields still agree with the new list
    assert start["pv_san"] == start["lines"][0]["pv_san"]
    assert start["alt"]["move_san"] == start["lines"][1]["move_san"]


def test_a_different_number_of_lines_is_a_different_analysis(client, db_factory):
    gid = make_game(client)
    one = analyze(client, db_factory, gid, multipv=1)
    review = client.get(f"/api/games/{gid}/analysis").json()
    assert len(review["positions"][0]["lines"]) == 1 and review["positions"][0]["alt"] is None

    three = analyze(client, db_factory, gid, multipv=3)  # not served from the 1-line review
    assert three["run_id"] != one["run_id"]
    assert len(client.get(f"/api/games/{gid}/analysis").json()["positions"][0]["lines"]) == 3
    r = request(client, gid, multipv=1)  # going back reuses the earlier review
    assert r.status_code == 200 and r.json()["run_id"] == one["run_id"]


def test_reviews_saved_before_multi_line_support_still_serve_two_lines(client, db_factory):
    gid = make_game(client)
    analyze(client, db_factory, gid)
    with db_factory() as db:  # simulate an old row: no `lines`, only the original columns
        db.execute(update(AnalysisPosition).values(lines=None))
        db.commit()
    start = client.get(f"/api/games/{gid}/analysis").json()["positions"][0]
    assert [ln["rank"] for ln in start["lines"]] == [1, 2]


def test_identical_settings_reuse_the_saved_review(client, db_factory):
    gid = make_game(client)
    first = analyze(client, db_factory, gid)

    r = request(client, gid)  # same settings
    assert r.status_code == 200 and r.json()["cached"] and r.json()["job"] is None
    assert r.json()["run_id"] == first["run_id"]
    assert count(db_factory, AnalysisJob) == 1  # no new work was queued

    second = analyze(client, db_factory, gid, depth=12)  # different settings: new run
    assert second["run_id"] != first["run_id"]
    assert client.get(f"/api/games/{gid}/analysis").json()["run"]["depth"] == 12

    r = request(client, gid)  # back to the first settings: reused, and re-selected
    assert r.status_code == 200 and r.json()["run_id"] == first["run_id"]
    assert client.get(f"/api/games/{gid}/analysis").json()["run"]["depth"] == 16
    assert count(db_factory, AnalysisRun, AnalysisRun.status == "completed") == 2


def test_failed_reanalysis_keeps_the_previous_review(client, db_factory):
    """AT-11 / NFR-02 / FR-08: a failed job must not corrupt a completed analysis."""
    gid = make_game(client)
    good = analyze(client, db_factory, gid)

    failed = analyze(client, db_factory, gid, FakeEngine(fail_at=3), depth=12)
    assert failed["status"] == "failed" and failed["error"]
    assert "boom" not in failed["error"]  # internal details are not leaked

    review = client.get(f"/api/games/{gid}/analysis").json()
    assert review["run"]["id"] == good["run_id"] and len(review["positions"]) == 7
    game = client.get(f"/api/games/{gid}").json()
    assert game["analysis_status"] == "completed"  # the old review is still valid
    assert game["latest_job"]["status"] == "failed"

    # The failed run left no partial rows behind and is marked failed.
    with db_factory() as db:
        bad = db.scalar(select(AnalysisRun).where(AnalysisRun.status == "failed"))
        assert bad is not None and bad.limit_depth == 12
        assert count(db_factory, AnalysisPosition, AnalysisPosition.run_id == bad.id) == 0

    # Retrying is safe and, once it succeeds, replaces the review atomically.
    retry = client.post(f"/api/jobs/{failed['id']}/retry")
    assert retry.status_code == 202 and retry.json()["job"]["id"] != failed["id"]
    assert runner_for(db_factory, FakeEngine()).run_once()
    assert client.get(f"/api/games/{gid}/analysis").json()["run"]["depth"] == 12


def test_engine_crash_is_retried_once_then_fails(client, db_factory):
    gid = make_game(client)
    job_id = request(client, gid).json()["job"]["id"]

    crashing = FakeEngine(fail_at=2, error=TERMINATED)
    runner = runner_for(db_factory, crashing)
    assert runner.run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "queued" and job["attempts"] == 1
    assert crashing.closed == 1  # the broken engine was discarded
    assert count(db_factory, AnalysisPosition) == 0

    assert runner_for(db_factory, FakeEngine(fail_at=2, error=TERMINATED)).run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["attempts"] == 2 and "engine failed" in job["error"]
    assert client.get(f"/api/games/{gid}/analysis").status_code == 404  # never shown as complete


def test_job_timeout_fails_explicitly(client, db_factory):
    gid = make_game(client)
    request(client, gid)
    # the limit is max(floor, positions * allowance): zero both so the very first position is late
    slow = runner_for(
        db_factory, FakeEngine(), analysis_job_timeout_seconds=-1, job_seconds_per_position=0
    )
    assert slow.run_once()
    job = client.get(f"/api/games/{gid}").json()["latest_job"]
    assert job["status"] == "failed" and "time limit" in job["error"]
    assert client.get(f"/api/games/{gid}/analysis").status_code == 404


def test_unevaluated_positions_never_become_a_review(client, db_factory):
    gid = make_game(client)
    job = analyze(client, db_factory, gid, FakeEngine(unavailable={3}))
    assert job["status"] == "failed" and "could not be evaluated" in job["error"]
    assert client.get(f"/api/games/{gid}/analysis").status_code == 404
    assert count(db_factory, AnalysisPosition) == 0


def test_shutdown_requeues_the_job_without_using_an_attempt(client, db_factory):
    gid = make_game(client)
    job_id = request(client, gid).json()["job"]["id"]
    stop = threading.Event()
    stop.set()
    assert runner_for(db_factory, FakeEngine(), stop=stop).run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "queued" and job["attempts"] == 0
    assert count(db_factory, AnalysisPosition) == 0


def test_a_worker_that_lost_its_job_does_not_overwrite_it(client, db_factory):
    """If the reaper reassigns a job mid-run, the original worker must back off."""
    gid = make_game(client)
    job_id = request(client, gid).json()["job"]["id"]

    def reaper_strikes(call: int) -> None:
        if call == 3:
            with db_factory() as db:
                db.execute(update(AnalysisJob).values(status="queued", locked_by=None))
                db.commit()

    assert runner_for(db_factory, FakeEngine(on_call=reaper_strikes)).run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "queued"  # the reaper's decision stands
    assert scalar(db_factory, select(Game.current_analysis_id)) is None
    assert count(db_factory, AnalysisPosition) == 0


# ---- crash recovery ---------------------------------------------------------------------


def _stale_job(client, db_factory, attempts: int, heartbeat_age: int):
    gid = make_game(client)
    job_id = request(client, gid).json()["job"]["id"]
    with db_factory() as db:
        job = db.get(AnalysisJob, job_id)
        run = AnalysisRun(
            game_id=job.game_id, status="running", engine_name="x", multipv=2, class_config={},
            class_config_hash="h", cache_key="k",
        )
        db.add(run)
        db.flush()
        db.add(AnalysisPosition(run_id=run.id, ply=0, fen="f"))
        job.status, job.attempts, job.run_id = "running", attempts, run.id
        job.locked_by = "dead-worker"
        job.heartbeat_at = utcnow() - timedelta(seconds=heartbeat_age)
        db.commit()
    return job_id


def test_reaper_requeues_a_dead_workers_job(client, db_factory):
    job_id = _stale_job(client, db_factory, attempts=1, heartbeat_age=600)
    with db_factory() as db:
        assert queue.reap_stale(db, stale_seconds=120) == [uuid.UUID(job_id)]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "queued"
    assert count(db_factory, AnalysisPosition) == 0  # partial results discarded
    assert scalar(db_factory, select(AnalysisRun.status)) == "failed"
    # ...and a healthy worker can now pick it up and finish it (AT-11).
    assert runner_for(db_factory, FakeEngine()).run_once()
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"


def test_reaper_fails_a_job_that_has_used_all_attempts(client, db_factory):
    job_id = _stale_job(client, db_factory, attempts=2, heartbeat_age=600)
    with db_factory() as db:
        queue.reap_stale(db, stale_seconds=120)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and "stopped responding" in job["error"]


def test_reaper_leaves_healthy_jobs_alone(client, db_factory):
    job_id = _stale_job(client, db_factory, attempts=1, heartbeat_age=5)
    with db_factory() as db:
        assert queue.reap_stale(db, stale_seconds=120) == []
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "running"


def test_watchdog_kills_a_hung_engine_only(db_factory):
    engine = FakeEngine()
    runner = runner_for(db_factory, engine)
    runner._active_engine = engine
    runner._last_progress = time.monotonic()
    assert not runner.check_hung() and not engine.killed
    runner._last_progress = time.monotonic() - 10_000
    assert runner.check_hung() and engine.killed
    runner._active_engine = None
    assert not runner.check_hung()


def test_concurrent_workers_never_claim_the_same_job(client, db_factory):
    for i in range(8):
        gid = make_game(client, f"P{i}")
        with db_factory() as db:
            game = db.get(Game, gid)
            db.add(AnalysisJob(game_id=game.id, owner_id=game.owner_id, status="queued", params={}))
            db.commit()

    claimed: list[list] = [[] for _ in range(4)]

    def work(slot: int) -> None:
        with db_factory() as db:
            while (job := queue.claim_next(db, f"w{slot}")) is not None:
                claimed[slot].append(job.id)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    all_ids = [j for slot in claimed for j in slot]
    assert len(all_ids) == 8 and len(set(all_ids)) == 8


# ---- access control & housekeeping ----------------------------------------------------------


def test_other_users_cannot_see_or_drive_my_analysis(make_client, db_factory):
    a, b = make_client(), make_client()
    gid = make_game(a)
    job = analyze(a, db_factory, gid, FakeEngine(fail_at=2))  # leaves a failed job
    assert job["status"] == "failed"

    assert b.get(f"/api/jobs/{job['id']}").status_code == 404
    assert b.post(f"/api/jobs/{job['id']}/retry").status_code == 404
    assert b.get(f"/api/games/{gid}/analysis").status_code == 404
    assert request(b, gid).status_code == 404
    assert a.get(f"/api/jobs/{job['id']}").status_code == 200


def test_only_failed_jobs_can_be_retried(client):
    gid = make_game(client)
    job_id = request(client, gid).json()["job"]["id"]
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_deleting_a_game_removes_its_analysis(client, db_factory):
    gid = make_game(client)
    analyze(client, db_factory, gid)
    assert count(db_factory, AnalysisPosition) == 7
    assert client.delete(f"/api/games/{gid}").status_code == 204
    for model in (AnalysisRun, AnalysisPosition, AnalysisJob):
        assert count(db_factory, model) == 0


def test_a_review_is_served_from_the_database_to_a_brand_new_client(client, db_factory):
    """AT-10 (in-process part): nothing needed lives in process memory, only in the database.
    The real restart is verified against the running containers."""
    gid = make_game(client)
    analyze(client, db_factory, gid)
    fresh = TestClient(client.app, headers=client.headers)
    fresh.cookies.update(client.cookies)
    assert fresh.get(f"/api/games/{gid}/analysis").json()["summary"]["complete"]
