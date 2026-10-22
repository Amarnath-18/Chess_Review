"""M6: settings, history filters, PGN export, data deletion and the retention purge."""
import io
from datetime import timedelta

import chess.pgn
import pytest
from sqlalchemy import func, select, update

from app.config import get_settings
from app.models.analysis import AnalysisJob, AnalysisPosition, AnalysisRun
from app.models.base import utcnow
from app.models.game import Game
from app.models.user import User, UserSession
from app.services.retention import purge_inactive
from tests.helpers import FakeEngine
from worker.runner import EngineHolder, JobRunner

GAME = """[Event "Casual"]
[Date "{date}"]
[White "{white}"]
[Black "{black}"]
[Result "{result}"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 {result}
"""


@pytest.fixture(autouse=True)
def fake_engine_name(monkeypatch):
    monkeypatch.setattr("app.services.analysis.service.get_engine_name", lambda: FakeEngine.name)


def add_game(client, white="Alice", black="Bob", date="2024.03.09", result="1-0") -> str:
    text = GAME.format(white=white, black=black, date=date, result=result)
    r = client.post("/api/imports/pgn", json={"pgn_text": text})
    assert r.status_code == 200, r.text
    return r.json()["imported"][0]["id"]


def run_job(db_factory, engine=None, **settings) -> bool:
    s = get_settings().model_copy(update=settings)
    return JobRunner(db_factory, EngineHolder(lambda: engine or FakeEngine()), "t", None, s).run_once()


def analyze(client, db_factory, gid, **body):
    assert client.post(f"/api/games/{gid}/analysis", json=body).status_code == 202
    assert run_job(db_factory)


def count(db_factory, model, *where):
    with db_factory() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


# ---- settings -------------------------------------------------------------------------------


def test_default_settings_describe_the_server_limits(client):
    body = client.get("/api/settings").json()
    s = get_settings()
    assert body == {
        "default_depth": s.default_depth,
        "default_multipv": s.default_multipv,
        "import_count": s.default_import_count,
        "max_depth": s.max_depth,
        "max_multipv": s.max_multipv,
        "retention_days": s.retention_days,
    }


def test_settings_can_be_changed_one_field_at_a_time_and_persist(client):
    r = client.put("/api/settings", json={"default_depth": 12})
    assert r.status_code == 200 and r.json()["default_depth"] == 12
    assert r.json()["default_multipv"] == get_settings().default_multipv  # untouched
    client.put("/api/settings", json={"default_multipv": 4, "import_count": 50})
    body = client.get("/api/settings").json()
    assert (body["default_depth"], body["default_multipv"], body["import_count"]) == (12, 4, 50)


def test_settings_are_private_to_each_user(make_client):
    a, b = make_client(), make_client()
    a.put("/api/settings", json={"default_depth": 9})
    assert b.get("/api/settings").json()["default_depth"] == get_settings().default_depth


@pytest.mark.parametrize(
    "body",
    [
        {"default_depth": 0},
        {"default_depth": 10_000},
        {"default_multipv": 0},
        {"default_multipv": 99},
        {"import_count": 15},
        {"default_depth": "deep"},
        {"unknown_setting": 1},  # unknown fields are refused, not silently dropped
        {"retention_days": 9999},  # server-owned values cannot be set by a user
    ],
)
def test_invalid_settings_are_refused_and_change_nothing(client, body):
    before = client.get("/api/settings").json()
    assert client.put("/api/settings", json=body).status_code == 422
    assert client.get("/api/settings").json() == before


def test_settings_need_a_session_and_the_csrf_header(make_client):
    c = make_client(start_session=False)
    assert c.get("/api/settings").status_code == 401
    assert c.put("/api/settings", json={"default_depth": 12}).status_code == 401


def test_a_saved_default_above_a_lowered_server_cap_is_clamped(client, monkeypatch):
    client.put("/api/settings", json={"default_depth": 20})
    monkeypatch.setattr(get_settings(), "max_depth", 14)  # the operator lowers the cap later
    assert client.get("/api/settings").json()["default_depth"] == 14


def test_analysis_uses_the_users_own_defaults_when_nothing_is_chosen(client):
    client.put("/api/settings", json={"default_depth": 12, "default_multipv": 2})
    gid = add_game(client)
    job = client.post(f"/api/games/{gid}/analysis").json()["job"]
    assert job["params"] == {"depth": 12, "nodes": None, "multipv": 2}


def test_an_explicit_choice_beats_the_users_defaults(client):
    client.put("/api/settings", json={"default_depth": 12, "default_multipv": 2})
    gid = add_game(client)
    job = client.post(f"/api/games/{gid}/analysis", json={"depth": 18, "multipv": 5}).json()["job"]
    assert job["params"] == {"depth": 18, "nodes": None, "multipv": 5}


def test_a_node_limited_request_does_not_also_get_a_default_depth(client):
    client.put("/api/settings", json={"default_depth": 12})
    gid = add_game(client)
    job = client.post(f"/api/games/{gid}/analysis", json={"nodes": 100000}).json()["job"]
    assert job["params"]["depth"] is None and job["params"]["nodes"] == 100000


# ---- history filters --------------------------------------------------------------------------


def test_filter_by_whether_a_game_has_been_analyzed(client, db_factory):
    done = add_game(client, "Done", "X")
    todo = add_game(client, "Todo", "Y")
    analyze(client, db_factory, done)
    ids = lambda q: [g["id"] for g in client.get(f"/api/games?{q}").json()["items"]]  # noqa: E731
    assert ids("analyzed=true") == [done]
    assert ids("analyzed=false") == [todo]
    assert sorted(ids("")) == sorted([done, todo])


def test_a_failed_analysis_does_not_count_as_analyzed(client, db_factory):
    gid = add_game(client)
    client.post(f"/api/games/{gid}/analysis", json={})
    assert run_job(db_factory, FakeEngine(fail_at=2))
    assert client.get("/api/games?analyzed=true").json()["total"] == 0
    assert client.get("/api/games?analyzed=false").json()["total"] == 1


def test_sort_by_game_date_or_by_import_order(client):
    first = add_game(client, "P1", "Q", date="2024.01.01")  # oldest game, imported first
    second = add_game(client, "P2", "Q", date="2025.06.01")  # newest game
    third = add_game(client, "P3", "Q", date="2023.01.01")  # oldest game, imported last
    order = lambda q: [g["id"] for g in client.get(f"/api/games?{q}").json()["items"]]  # noqa: E731
    assert order("") == [second, first, third]  # by when it was played, newest first
    assert order("sort=played") == [second, first, third]
    assert order("sort=added") == [third, second, first]  # most recently imported first
    assert client.get("/api/games?sort=bogus").status_code == 422


def test_filters_combine_and_total_reflects_them(client):
    for i in range(5):
        add_game(client, f"Alice{i}", "Bob", date=f"2024.0{i + 1}.01", result="1-0" if i % 2 else "0-1")
    r = client.get("/api/games?q=alice&result=1-0&date_from=2024-02-01&page_size=1&page=2").json()
    assert r["total"] == 2 and len(r["items"]) == 1 and r["page"] == 2
    assert client.get("/api/games?q=zzz").json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


# ---- PGN export ---------------------------------------------------------------------------------


def parse_all(text: str):
    handle = io.StringIO(text)
    games = []
    while (g := chess.pgn.read_game(handle)) is not None:
        games.append(g)
    return games


def test_download_one_game_as_pgn(client):
    gid = add_game(client, "Alice", "Bob")
    r = client.get(f"/api/games/{gid}/pgn")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-chess-pgn")
    assert r.headers["content-disposition"] == 'attachment; filename="Alice-vs-Bob-2024-03-09.pgn"'
    (game,) = parse_all(r.text)
    assert game.headers["White"] == "Alice" and len(list(game.mainline_moves())) == 6


def test_download_filenames_are_always_safe(client):
    gid = add_game(client, 'Ünï/cøde ".."\r\nX-Evil: 1', "../../etc/passwd")
    disposition = client.get(f"/api/games/{gid}/pgn").headers["content-disposition"]
    name = disposition.split('filename="')[1].rstrip('"')
    assert name.isascii() and "/" not in name and "\r" not in disposition and "\n" not in disposition
    assert name.endswith(".pgn") and ".." not in name.rsplit(".pgn", 1)[0].replace("-", "")


def test_a_game_that_is_not_yours_cannot_be_downloaded(make_client):
    a, b = make_client(), make_client()
    gid = add_game(a)
    assert b.get(f"/api/games/{gid}/pgn").status_code == 404
    assert make_client(start_session=False).get(f"/api/games/{gid}/pgn").status_code == 401


def test_export_all_games_in_one_file(client):
    add_game(client, "Alice", "Bob", date="2024.01.01")
    add_game(client, "Carol", "Dave", date="2024.05.01")
    r = client.get("/api/games/export")
    assert r.status_code == 200
    assert r.headers["x-game-count"] == "2"
    assert r.headers["content-disposition"].startswith('attachment; filename="chess-review-games-')
    games = parse_all(r.text)
    assert [g.headers["White"] for g in games] == ["Carol", "Alice"]  # newest game first


def test_export_honours_the_same_filters_as_the_list(client):
    add_game(client, "Alice", "Bob", result="1-0")
    add_game(client, "Alice", "Carol", result="0-1")
    add_game(client, "Dave", "Erin", result="1-0")
    r = client.get("/api/games/export?q=alice&result=1-0")
    assert r.headers["x-game-count"] == "1"
    (game,) = parse_all(r.text)
    assert (game.headers["White"], game.headers["Black"]) == ("Alice", "Bob")


def test_export_with_nothing_to_export_is_a_clear_404(client):
    assert client.get("/api/games/export").status_code == 404
    add_game(client)
    r = client.get("/api/games/export?q=nobody")
    assert r.status_code == 404 and "nothing to export" in r.json()["detail"]


def test_export_refuses_more_than_the_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "export_max_games", 1)
    add_game(client, "A1", "B")
    add_game(client, "A2", "B")
    r = client.get("/api/games/export")
    assert r.status_code == 422 and "at most 1" in r.json()["detail"]
    assert client.get("/api/games/export?q=a1").status_code == 200


def test_export_never_includes_other_users_games(make_client):
    a, b = make_client(), make_client()
    add_game(a, "Alice", "Bob")
    add_game(b, "Mine", "Only")
    games = parse_all(b.get("/api/games/export").text)
    assert [g.headers["White"] for g in games] == ["Mine"]


def test_exported_games_can_be_imported_again_unchanged(make_client):
    """Round trip: what you export is what you can bring back (and duplicates are recognised)."""
    a, b = make_client(), make_client()
    for i in range(3):
        add_game(a, f"Player{i}", "Opp", date=f"2024.0{i + 1}.15")
    exported = a.get("/api/games/export").text
    r = b.post("/api/imports/pgn", json={"pgn_text": exported})
    assert r.status_code == 200 and len(r.json()["imported"]) == 3 and not r.json()["errors"]
    again = a.post("/api/imports/pgn", json={"pgn_text": exported}).json()
    assert not again["imported"] and len(again["duplicates"]) == 3


def test_the_export_route_is_not_mistaken_for_a_game_id(client):
    assert client.get("/api/games/export").status_code in (200, 404)  # never a 422 uuid error
    assert client.get("/api/games/not-a-uuid").status_code == 422


# ---- deleting my data -----------------------------------------------------------------------------


def test_delete_all_my_games_keeps_the_session_and_settings(client, db_factory):
    client.put("/api/settings", json={"default_depth": 12})
    analyzed = add_game(client, "A", "B")
    add_game(client, "C", "D")
    analyze(client, db_factory, analyzed)
    assert count(db_factory, AnalysisPosition) > 0

    r = client.delete("/api/me/games")
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert client.get("/api/games").json()["total"] == 0
    for model in (AnalysisRun, AnalysisPosition, AnalysisJob):
        assert count(db_factory, model) == 0
    assert client.get("/api/settings").json()["default_depth"] == 12  # still signed in, settings kept
    assert client.delete("/api/me/games").json() == {"deleted": 0}  # safe to repeat


def test_delete_all_games_leaves_other_users_alone(make_client, db_factory):
    a, b = make_client(), make_client()
    add_game(a)
    kept = add_game(b)
    a.delete("/api/me/games")
    assert b.get(f"/api/games/{kept}").status_code == 200


def test_delete_everything_removes_the_user_and_signs_out(client, db_factory):
    client.put("/api/settings", json={"default_depth": 12})
    gid = add_game(client)
    analyze(client, db_factory, gid)

    r = client.delete("/api/me")
    assert r.status_code == 204
    assert "sid=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    for model in (User, UserSession, Game, AnalysisRun, AnalysisPosition, AnalysisJob):
        assert count(db_factory, model) == 0, model
    client.cookies.clear()  # the browser drops the expired cookie
    assert client.get("/api/games").status_code == 401  # the old session is gone for good
    fresh = client.post("/api/session")  # a new anonymous user starts clean
    assert fresh.json()["new"] is True
    assert client.get("/api/settings").json()["default_depth"] == get_settings().default_depth


def test_delete_everything_does_not_touch_other_users(make_client, db_factory):
    a, b = make_client(), make_client()
    add_game(a)
    kept = add_game(b)
    a.delete("/api/me")
    assert b.get(f"/api/games/{kept}").status_code == 200


def test_deleting_a_game_while_it_is_being_analyzed_is_harmless(client, db_factory):
    """The worker must neither crash nor leave rows behind."""
    gid = add_game(client)
    client.post(f"/api/games/{gid}/analysis", json={})

    def delete_midway(call: int) -> None:
        if call == 3:
            assert client.delete(f"/api/games/{gid}").status_code == 204

    assert run_job(db_factory, FakeEngine(on_call=delete_midway))  # returns normally
    for model in (Game, AnalysisRun, AnalysisPosition, AnalysisJob):
        assert count(db_factory, model) == 0, model


def test_deleting_everything_while_a_job_is_queued_is_harmless(client, db_factory):
    gid = add_game(client)
    client.post(f"/api/games/{gid}/analysis", json={})
    client.delete("/api/me")
    assert run_job(db_factory) is False  # nothing left to run
    assert count(db_factory, AnalysisJob) == 0


# ---- retention purge --------------------------------------------------------------------------------


def make_old(db_factory, client, days: float):
    user_id = client.post("/api/session").json()["user_id"]
    with db_factory() as db:
        db.execute(update(User).where(User.id == user_id).values(last_seen_at=utcnow() - timedelta(days=days)))
        db.commit()
    return user_id


def test_inactive_users_are_deleted_with_everything_they_own(make_client, db_factory):
    old, recent = make_client(), make_client()
    add_game(old, "Old", "Player")
    analyzed = add_game(old, "Old2", "Player")
    analyze(old, db_factory, analyzed)
    kept = add_game(recent, "Recent", "Player")
    make_old(db_factory, old, days=31)

    with db_factory() as db:
        result = purge_inactive(db, retention_days=30)
    assert (result.users, result.games) == (1, 2)
    for model in (AnalysisRun, AnalysisPosition, AnalysisJob):
        assert count(db_factory, model) == 0
    assert count(db_factory, User) == 1 and count(db_factory, Game) == 1
    assert recent.get(f"/api/games/{kept}").status_code == 200
    assert old.get("/api/games").status_code == 401  # their session went with them


def test_the_cutoff_is_exact(make_client, db_factory):
    inside, outside = make_client(), make_client()
    add_game(inside)
    add_game(outside)
    now = utcnow()
    for c, delta in ((inside, timedelta(days=30) - timedelta(minutes=1)), (outside, timedelta(days=30) + timedelta(minutes=1))):
        uid = c.post("/api/session").json()["user_id"]
        with db_factory() as db:
            db.execute(update(User).where(User.id == uid).values(last_seen_at=now - delta))
            db.commit()
    with db_factory() as db:
        assert purge_inactive(db, retention_days=30, now=now).users == 1
    assert inside.get("/api/games").json()["total"] == 1


def test_visiting_keeps_data_alive(make_client, db_factory):
    c = make_client()
    add_game(c)
    make_old(db_factory, c, days=29)
    assert c.get("/api/games").status_code == 200  # a visit slides the clock forward
    with db_factory() as db:
        assert db.scalar(select(User.last_seen_at)) > utcnow() - timedelta(days=1)
        assert purge_inactive(db, retention_days=1).users == 0


def test_expired_session_rows_are_removed_but_the_user_stays(make_client, db_factory):
    c = make_client()
    add_game(c)
    with db_factory() as db:
        db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    with db_factory() as db:
        result = purge_inactive(db, retention_days=30)
    assert result.expired_sessions == 1 and result.users == 0
    assert count(db_factory, UserSession) == 0 and count(db_factory, Game) == 1


def test_retention_can_be_switched_off(make_client, db_factory):
    c = make_client()
    add_game(c)
    make_old(db_factory, c, days=999)
    with db_factory() as db:
        assert purge_inactive(db, retention_days=0).users == 0
        assert purge_inactive(db, retention_days=-5).users == 0
    assert count(db_factory, User) == 1


def test_the_worker_purges_on_a_schedule(make_client, db_factory, monkeypatch):
    c = make_client()
    add_game(c)
    make_old(db_factory, c, days=60)
    calls = []
    real = purge_inactive
    monkeypatch.setattr("worker.runner.purge_inactive", lambda db, days: calls.append(days) or real(db, days))

    runner = JobRunner(
        db_factory, EngineHolder(FakeEngine), "t", None,
        get_settings().model_copy(update={"retention_days": 30, "retention_purge_interval_seconds": 3600}),
    )
    runner.maintenance()
    runner.maintenance()  # within the interval: no second purge
    assert calls == [30]
    assert count(db_factory, User) == 0 and count(db_factory, Game) == 0

    runner.settings = runner.settings.model_copy(update={"retention_purge_interval_seconds": 0})
    runner.maintenance()
    assert calls == [30, 30]
