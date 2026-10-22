"""The time estimate endpoint and its calibration against real runs."""
import uuid
from datetime import timedelta

import pytest

from app.config import get_settings
from app.models.analysis import AnalysisRun
from app.models.base import utcnow
from app.services.analysis.estimate import UNCERTAINTY, seconds_per_position

GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "{white}"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""  # 6 plies -> 7 positions


def add(client, white="Alice") -> str:
    r = client.post("/api/imports/pgn", json={"pgn_text": GAME.format(white=white)})
    return r.json()["imported"][0]["id"]


def estimate(client, gid, **params):
    return client.get(f"/api/games/{gid}/analysis/estimate", params=params)


def model(depth, lines, positions=7):
    return positions * seconds_per_position(depth, lines)


def add_runs(db_factory, game_id, count, factor, depth=16, lines=3, status="completed", plies=6, age=0):
    """Insert finished runs that took `factor` times what the model predicts."""
    predicted = (plies + 1) * seconds_per_position(depth, lines)
    with db_factory() as db:
        for i in range(count):
            finished = utcnow() - timedelta(minutes=age + i)
            db.add(
                AnalysisRun(
                    game_id=game_id,
                    status=status,
                    engine_name="Stockfish 17.1",
                    limit_depth=depth,
                    multipv=lines,
                    class_config={},
                    class_config_hash="h",
                    cache_key=uuid.uuid4().hex,
                    started_at=finished - timedelta(seconds=predicted * factor),
                    finished_at=finished,
                )
            )
        db.commit()


# ---- the estimate ---------------------------------------------------------------------------


def test_without_history_the_estimate_is_the_model(client):
    gid = add(client)
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["seconds"] == pytest.approx(model(16, 3))
    assert body["positions"] == 7 and body["calibrated_from_runs"] == 0
    assert body["limit_seconds"] == 600 and body["exceeds_limit"] is False
    # an honest range around the guess, never a single confident number
    assert body["seconds_low"] == pytest.approx(body["seconds"] / UNCERTAINTY)
    assert body["seconds_high"] == pytest.approx(body["seconds"] * UNCERTAINTY)
    assert body["seconds_low"] < body["seconds"] < body["seconds_high"]


def test_omitted_settings_default_to_the_users_own(client):
    gid = add(client)
    client.put("/api/settings", json={"default_depth": 12, "default_multipv": 2})
    assert estimate(client, gid).json()["seconds"] == pytest.approx(model(12, 2))
    assert estimate(client, gid, depth=14).json()["seconds"] == pytest.approx(model(14, 2))
    assert estimate(client, gid, multipv=5).json()["seconds"] == pytest.approx(model(12, 5))


def test_a_node_limited_search_is_not_estimated(client):
    gid = add(client)
    body = estimate(client, gid, nodes=100000).json()
    assert body["seconds"] is None and body["exceeds_limit"] is False


def test_more_depth_and_more_lines_cost_more(client):
    gid = add(client)
    cost = lambda **p: estimate(client, gid, **p).json()["seconds"]  # noqa: E731
    assert cost(depth=10, multipv=1) < cost(depth=14, multipv=1) < cost(depth=18, multipv=1)
    assert cost(depth=16, multipv=1) < cost(depth=16, multipv=3) < cost(depth=16, multipv=5)


# ---- calibration ----------------------------------------------------------------------------------


def test_the_estimate_follows_how_long_real_runs_took(client, db_factory):
    gid = add(client)
    add_runs(db_factory, gid, count=4, factor=2.0)  # this server is twice as slow as the model
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["seconds"] == pytest.approx(2 * model(16, 3), rel=0.02)
    assert body["calibrated_from_runs"] == 4


def test_too_little_history_is_ignored(client, db_factory):
    gid = add(client)
    add_runs(db_factory, gid, count=2, factor=4.0)
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["seconds"] == pytest.approx(model(16, 3)) and body["calibrated_from_runs"] == 2


@pytest.mark.parametrize("factor, expected", [(100.0, 5.0), (0.001, 0.2)])
def test_calibration_is_clamped(client, db_factory, factor, expected):
    gid = add(client)
    add_runs(db_factory, gid, count=5, factor=factor)
    assert estimate(client, gid, depth=16, multipv=3).json()["seconds"] == pytest.approx(
        expected * model(16, 3), rel=0.02
    )


def test_failed_and_node_limited_runs_do_not_count(client, db_factory):
    gid = add(client)
    add_runs(db_factory, gid, count=5, factor=3.0, status="failed")
    with db_factory() as db:  # a node-limited run has no depth
        for _ in range(5):
            db.add(
                AnalysisRun(
                    game_id=gid, status="completed", engine_name="x", limit_depth=None,
                    limit_nodes=1000, multipv=3, class_config={}, class_config_hash="h",
                    cache_key=uuid.uuid4().hex, started_at=utcnow() - timedelta(seconds=999),
                    finished_at=utcnow(),
                )
            )
        db.commit()
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["calibrated_from_runs"] == 0 and body["seconds"] == pytest.approx(model(16, 3))


def test_only_the_most_recent_runs_are_used(client, db_factory):
    gid = add(client)
    add_runs(db_factory, gid, count=10, factor=3.0, age=0)  # the ten latest
    add_runs(db_factory, gid, count=20, factor=1.0, age=60)  # older, ignored
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["calibrated_from_runs"] == 10
    assert body["seconds"] == pytest.approx(3 * model(16, 3), rel=0.02)


def test_calibration_works_across_depths_and_line_counts(client, db_factory):
    """Runs at other settings still tell us about the machine, because the model scales them."""
    gid = add(client)
    add_runs(db_factory, gid, count=3, factor=2.0, depth=12, lines=1)
    add_runs(db_factory, gid, count=3, factor=2.0, depth=18, lines=5, age=10)
    assert estimate(client, gid, depth=14, multipv=2).json()["seconds"] == pytest.approx(
        2 * model(14, 2), rel=0.02
    )


# ---- the time limit -----------------------------------------------------------------------------------


def test_the_estimate_warns_when_a_run_would_be_stopped(client, monkeypatch):
    gid = add(client)
    monkeypatch.setattr(get_settings(), "analysis_job_timeout_seconds", 10)
    monkeypatch.setattr(get_settings(), "job_seconds_per_position", 1.0)
    quick = estimate(client, gid, depth=10, multipv=1).json()
    slow = estimate(client, gid, depth=22, multipv=5).json()
    assert quick["limit_seconds"] == 10
    assert quick["exceeds_limit"] is False and quick["may_exceed_limit"] is False
    assert slow["exceeds_limit"] is True and slow["seconds"] > slow["limit_seconds"]
    assert slow["may_exceed_limit"] is True  # if even the guess is over, so is the top of the range


def test_a_run_that_only_might_exceed_the_limit_is_flagged_but_not_blocked(client, monkeypatch):
    gid = add(client)
    guess = model(16, 3)  # about 7 s for these 7 positions
    monkeypatch.setattr(get_settings(), "job_seconds_per_position", 0)
    monkeypatch.setattr(get_settings(), "analysis_job_timeout_seconds", int(guess * 1.5))
    body = estimate(client, gid, depth=16, multipv=3).json()
    assert body["seconds"] < body["limit_seconds"] < body["seconds_high"]
    assert body["exceeds_limit"] is False and body["may_exceed_limit"] is True


def test_the_limit_in_the_estimate_is_the_one_the_worker_uses(client):
    from app.services.analysis.estimate import job_time_limit

    gid = add(client)
    assert estimate(client, gid).json()["limit_seconds"] == job_time_limit(7)


# ---- access and validation ------------------------------------------------------------------------------


def test_other_users_games_cannot_be_estimated(make_client):
    a, b = make_client(), make_client()
    gid = add(a)
    assert estimate(b, gid).status_code == 404
    assert estimate(make_client(start_session=False), gid).status_code == 401


@pytest.mark.parametrize("params", [{"depth": 0}, {"depth": 9999}, {"multipv": 0}, {"multipv": 99}, {"nodes": 0}])
def test_invalid_settings_are_refused(client, params):
    gid = add(client)
    assert estimate(client, gid, **params).status_code == 422
