"""Analyze-all batches (M9.1): fair feeding, cancel, ownership, failure handling."""
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models.analysis import AnalysisJob, AnalysisRun
from app.models.batch import BatchGame
from app.services.analysis import batches as batch_svc
from app.services.jobs import queue
from tests.helpers import FakeEngine
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


def runner_for(db_factory, engine=None) -> JobRunner:
    engine = engine or FakeEngine()
    return JobRunner(db_factory, EngineHolder(lambda: engine), "test-worker", None, get_settings())


def drain(db_factory, engine=None, limit=40) -> int:
    """Run the worker until it has nothing left to do (jobs and batch feeding included)."""
    runner = runner_for(db_factory, engine)
    n = 0
    while runner.run_once():
        n += 1
        assert n < limit, "worker never went idle"
    return n


def create(client, **body):
    return client.post("/api/analysis/batches", json=body)


def states(batch) -> list[str]:
    return [i["state"] for i in batch["items"]]


def test_batch_analyzes_every_game_and_finishes(client, db_factory):
    ids = [make_game(client, w) for w in ("A1", "A2", "A3")]
    r = create(client, game_ids=ids, depth=8, multipv=2)
    assert r.status_code == 201
    batch = r.json()
    assert batch["status"] == "running" and batch["total"] == 3
    # only one game is queued at first: a batch never takes the person's last free slot
    assert batch["counts"]["queued"] == 1 and batch["counts"]["pending"] == 2

    assert drain(db_factory) == 3
    final = client.get(f"/api/analysis/batches/{batch['id']}").json()
    assert final["status"] == "completed" and final["finished_at"]
    assert states(final) == ["done"] * 3 and final["counts"]["done"] == 3
    for gid in ids:
        assert client.get(f"/api/games/{gid}").json()["has_analysis"] is True
    assert client.get("/api/analysis/batches/latest").json()["id"] == batch["id"]


def test_a_single_game_can_still_be_analyzed_while_a_batch_runs(client, db_factory):
    ids = [make_game(client, w) for w in ("B1", "B2", "B3")]
    assert create(client, game_ids=ids[:2], depth=8).status_code == 201
    one = client.post(f"/api/games/{ids[2]}/analysis", json={"depth": 8})
    assert one.status_code == 202  # the batch left one slot free


def test_only_unanalyzed_games_by_default(client, db_factory):
    a, b = make_game(client, "C1"), make_game(client, "C2")
    client.post(f"/api/games/{a}/analysis", json={"depth": 8})
    drain(db_factory)
    r = create(client, game_ids=[a, b], depth=8)
    assert [i["game_id"] for i in r.json()["items"]] == [b]
    drain(db_factory)
    # nothing left to do: a clear message, not an empty batch
    again = create(client, game_ids=[a, b], depth=8)
    assert again.status_code == 422 and "no games" in again.json()["detail"].lower()
    # with the box unticked, analyzed games are included again
    redo = create(client, game_ids=[a], depth=9, only_unanalyzed=False)
    assert redo.status_code == 201


def test_filter_selects_the_games(client, db_factory):
    a, b = make_game(client, "D1"), make_game(client, "D2")
    client.patch(f"/api/games/{b}", json={"tags": ["study"]})
    r = create(client, filter={"tag": "study"}, depth=8)
    assert r.status_code == 201 and [i["game_id"] for i in r.json()["items"]] == [b]
    assert a


def test_estimate_before_starting(client):
    ids = [make_game(client, w) for w in ("E1", "E2")]
    r = client.post("/api/analysis/batches/estimate", json={"game_ids": ids, "depth": 12, "multipv": 1})
    body = r.json()
    assert r.status_code == 200 and body["games"] == 2 and body["positions"] == 14
    assert body["seconds_low"] < body["seconds"] < body["seconds_high"]
    assert body["too_many"] is False and body["max_games"] == get_settings().batch_max_games
    # nothing was queued by asking
    assert client.get("/api/analysis/batches/latest").json() is None


def test_only_one_running_batch_per_person(client):
    ids = [make_game(client, w) for w in ("F1", "F2")]
    assert create(client, game_ids=[ids[0]], depth=8).status_code == 201
    second = create(client, game_ids=[ids[1]], depth=8)
    assert second.status_code == 409 and "already" in second.json()["detail"]


def test_cancel_drops_waiting_games_and_keeps_existing_reviews(client, db_factory):
    keep, w1, w2 = make_game(client, "G1"), make_game(client, "G2"), make_game(client, "G3")
    client.post(f"/api/games/{keep}/analysis", json={"depth": 8})
    drain(db_factory)
    before = client.get(f"/api/games/{keep}/analysis").json()["run"]["id"]

    batch = create(client, game_ids=[keep, w1, w2], depth=10, only_unanalyzed=False).json()
    assert batch["counts"]["queued"] == 1
    out = client.post(f"/api/analysis/batches/{batch['id']}/cancel").json()
    assert out["status"] == "cancelled" and set(states(out)) == {"cancelled"}

    assert drain(db_factory) == 0  # the cancelled job is never picked up
    assert client.get(f"/api/games/{w1}").json()["has_analysis"] is False
    # the review that existed before is untouched
    assert client.get(f"/api/games/{keep}/analysis").json()["run"]["id"] == before
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "cancelled")) == 1
    # a new batch can start after cancelling
    assert create(client, game_ids=[w1], depth=8).status_code == 201


def test_cancelling_a_running_job_stops_it_without_saving_a_review(client, db_factory, monkeypatch):
    gid = make_game(client, "H1")
    batch = create(client, game_ids=[gid], depth=8).json()
    seen = {}
    real = queue.heartbeat

    def spy(db, job_id, worker_id, done=None, **kw):
        if done == 3 and "cancel" not in seen:  # three positions are done: the user cancels
            seen["cancel"] = client.post(f"/api/analysis/batches/{batch['id']}/cancel").json()
        return real(db, job_id, worker_id, done=done, **kw)

    monkeypatch.setattr(queue, "heartbeat", spy)
    drain(db_factory)

    assert seen["cancel"]["status"] == "cancelled"
    assert client.get(f"/api/games/{gid}").json()["has_analysis"] is False
    with db_factory() as db:
        job = db.scalar(select(AnalysisJob))
        assert job.status == "cancelled"
        assert db.scalar(select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status == "completed")) == 0


def test_a_failed_game_is_reported_and_the_rest_continue(client, db_factory):
    ids = [make_game(client, w) for w in ("I1", "I2")]
    create(client, game_ids=ids, depth=8)
    # the engine hits an error on every call of the first job (and its retry), then is fine
    bad = FakeEngine(fail_at=1, error=ValueError("cannot evaluate"))
    runner = runner_for(db_factory, bad)
    assert runner.run_once()  # first game fails (ValueError is not retried)
    drain(db_factory)
    batch = client.get("/api/analysis/batches/latest").json()
    assert batch["status"] == "completed"
    assert states(batch) == ["failed", "done"]
    assert batch["items"][0]["message"]


def test_games_that_cannot_be_analyzed_are_skipped_with_a_reason(client, db_factory, monkeypatch):
    ids = [make_game(client, w) for w in ("J1", "J2")]
    real = batch_svc.skip_reason

    def picky(db, game, params):
        return "Too long (test)." if game.white == "J1" else real(db, game, params)

    monkeypatch.setattr(batch_svc, "skip_reason", picky)
    r = create(client, game_ids=ids, depth=8).json()
    by_name = {i["white"]: i for i in r["items"]}
    assert by_name["J1"]["state"] == "skipped" and by_name["J1"]["message"] == "Too long (test)."
    assert by_name["J2"]["state"] == "queued"
    drain(db_factory)
    assert client.get("/api/analysis/batches/latest").json()["status"] == "completed"


def test_too_many_games_is_refused(client, monkeypatch):
    ids = [make_game(client, w) for w in ("K1", "K2", "K3")]
    monkeypatch.setattr(batch_svc, "get_settings", lambda: get_settings().model_copy(update={"batch_max_games": 2}))
    r = create(client, game_ids=ids, depth=8)
    assert r.status_code == 422 and "at most 2" in r.json()["detail"]


def test_batches_are_private(client, make_client):
    gid = make_game(client, "L1")
    batch = create(client, game_ids=[gid], depth=8).json()
    other = make_client()
    assert other.get(f"/api/analysis/batches/{batch['id']}").status_code == 404
    assert other.post(f"/api/analysis/batches/{batch['id']}/cancel").status_code == 404
    assert other.get("/api/analysis/batches/latest").json() is None
    assert create(other, game_ids=[gid], depth=8).status_code == 404  # someone else's game


def test_deleting_a_game_removes_it_from_the_batch(client, db_factory):
    ids = [make_game(client, w) for w in ("M1", "M2")]
    batch = create(client, game_ids=ids, depth=8).json()
    client.delete(f"/api/games/{ids[1]}")
    drain(db_factory)
    final = client.get(f"/api/analysis/batches/{batch['id']}").json()
    assert final["status"] == "completed" and final["total"] == 1
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(BatchGame)) == 1


# ---- 9.2 analyze new games automatically ------------------------------------------------


def test_auto_analyze_is_off_by_default_and_a_setting(client):
    assert client.get("/api/settings").json()["auto_analyze"] is False
    r = client.post("/api/imports/pgn", json={"pgn_text": GAME})
    assert r.json()["auto_analyzing"] == 0
    assert client.get("/api/analysis/batches/latest").json() is None
    assert client.put("/api/settings", json={"auto_analyze": True}).json()["auto_analyze"] is True
    assert client.put("/api/settings", json={"auto_analyze": "yes"}).status_code == 422


def test_auto_analyze_queues_exactly_the_new_games(client, db_factory):
    client.put("/api/settings", json={"auto_analyze": True, "default_depth": 8, "default_multipv": 2})
    two = GAME + "\n" + GAME.replace("Alice", "Zed")
    r = client.post("/api/imports/pgn", json={"pgn_text": two}).json()
    assert len(r["imported"]) == 2 and r["auto_analyzing"] == 2
    batch = client.get("/api/analysis/batches/latest").json()
    assert batch["status"] == "running" and batch["total"] == 2
    assert batch["params"]["depth"] == 8 and batch["params"]["multipv"] == 2

    # importing the same games again adds nothing (they are duplicates, not new)
    again = client.post("/api/imports/pgn", json={"pgn_text": two}).json()
    assert again["imported"] == [] and again["auto_analyzing"] == 0

    drain(db_factory)
    assert client.get("/api/analysis/batches/latest").json()["counts"]["done"] == 2
    ids = [g["id"] for g in r["imported"]]
    assert all(client.get(f"/api/games/{i}").json()["has_analysis"] for i in ids)


def test_auto_analyze_joins_a_running_batch_and_is_capped(client, db_factory, monkeypatch):
    client.put("/api/settings", json={"auto_analyze": True, "default_depth": 8})
    monkeypatch.setattr(
        "app.services.analysis.batches.get_settings",
        lambda: get_settings().model_copy(update={"auto_analyze_max_per_import": 2}),
    )
    games = "\n".join(GAME.replace("Alice", f"P{i}") for i in range(4))
    r = client.post("/api/imports/pgn", json={"pgn_text": games}).json()
    assert len(r["imported"]) == 4 and r["auto_analyzing"] == 2  # capped, and says so

    more = client.post("/api/imports/pgn", json={"pgn_text": GAME.replace("Alice", "Q")}).json()
    assert more["auto_analyzing"] == 1
    batch = client.get("/api/analysis/batches/latest").json()
    assert batch["total"] == 3  # the new game joined the same batch


def test_auto_analyze_never_fails_the_import(client, monkeypatch):
    client.put("/api/settings", json={"auto_analyze": True})

    def boom(*a, **k):
        raise batch_svc.BatchError(409, "x")

    monkeypatch.setattr(batch_svc, "create", boom)
    r = client.post("/api/imports/pgn", json={"pgn_text": GAME})
    assert r.status_code == 200 and len(r.json()["imported"]) == 1 and r.json()["auto_analyzing"] == 0
