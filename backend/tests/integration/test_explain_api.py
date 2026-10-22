"""AI explanations: consent, limits, caching, outages and privacy (M11), with a fake model."""
import json

import pytest
from sqlalchemy import func, select

from app.api import access as access_api
from app.config import get_settings
from app.models.explanation import LlmUsage, MoveExplanation
from app.services.explain import service
from app.services.explain.client import Completion, LlmUnavailable
from app.services.invites import create as create_invite
from tests.helpers import seed_review

GAME = """[Event "Casual"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. a3 e5 2. e4 Nc6 3. Nf3 Bc5 1-0
"""

CLEAR = [(300, ["e2e4", "e7e5"]), (0, ["d2d4"]), (-50, ["g1f3"])]
SPECS = {
    0: {"lines": CLEAR},
    1: {"cls": "blunder", "loss": 34.0, "cp": -100, "lines": [(-100, ["e7e5"])]},
    2: {"cp": -50, "lines": [(-50, ["e2e4"]), (-90, ["d2d4"])]},
    3: {"cls": "mistake", "loss": 12.0, "cp": -90, "lines": [(-90, ["b8c6"])]},
}
GOOD = json.dumps(
    {"explanation": "You played a3, but e4 was the engine's choice and gained more.", "mentioned_moves": ["a3", "e4"], "motif": None}
)
INVENTED = json.dumps({"explanation": "You should play Qh5 here.", "mentioned_moves": ["Qh5"], "motif": None})


class FakeClient:
    model = "fake-model"
    instances: list = []

    def __init__(self, *_a, **_k):
        pass

    replies: list = []
    seen: list = []
    error = None

    def complete(self, messages):
        FakeClient.seen.append(messages)
        if FakeClient.error:
            raise FakeClient.error
        text = FakeClient.replies.pop(0) if FakeClient.replies else GOOD
        return Completion(text, 120, 30, 0.8)


@pytest.fixture(autouse=True)
def model(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(s, "llm_api_key", "test-key")
    monkeypatch.setattr(s, "llm_model", "fake-model")
    monkeypatch.setattr(s, "llm_provider_label", "")
    monkeypatch.setattr(s, "explain_daily_limit_per_user", 30)
    monkeypatch.setattr(s, "llm_requests_per_minute", 0)
    monkeypatch.setattr(service, "OpenAICompatibleClient", FakeClient)
    FakeClient.replies, FakeClient.seen, FakeClient.error = [], [], None
    service._requests.clear()
    access_api.ATTEMPTS.clear()
    yield
    service._requests.clear()


def reviewed_game(client, db_factory, white="Alice"):
    gid = client.post("/api/imports/pgn", json={"pgn_text": GAME.replace("Alice", white)}).json()["imported"][0]["id"]
    seed_review(db_factory, gid, SPECS)
    return gid


def opt_in(client, **extra):
    r = client.put("/api/settings", json={"ai_explanations": True, **extra})
    assert r.status_code == 200
    return r.json()


def ask(client, gid, ply=1):
    return client.post(f"/api/games/{gid}/explain/{ply}")


# ---- consent and set-up ----------------------------------------------------------------


def test_settings_describe_what_the_server_offers_and_start_off(client):
    s = client.get("/api/settings").json()
    assert s["ai_available"] is True and s["ai_explanations"] is False
    assert s["explain_level"] == "intermediate" and s["ai_provider"] == "OpenRouter"
    assert s["explain_daily_limit"] == 30
    assert client.put("/api/settings", json={"explain_level": "expert"}).status_code == 422
    assert client.put("/api/settings", json={"ai_explanations": "yes"}).status_code == 422


def test_a_hosted_provider_is_named_in_the_settings(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider_label", "Groq (hosted)")
    s = client.get("/api/settings").json()
    assert s["ai_provider"] == "Groq (hosted)"


def test_not_configured_means_no_explanations(client, db_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_api_key", "")
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    r = ask(client, gid)
    assert r.status_code == 503 and "not set up" in r.json()["detail"]
    assert client.get("/api/settings").json()["ai_available"] is False


def test_off_until_the_person_opts_in(client, db_factory):
    gid = reviewed_game(client, db_factory)
    r = ask(client, gid)
    assert r.status_code == 403 and "Settings" in r.json()["detail"]
    assert FakeClient.seen == []  # nothing was sent anywhere


# ---- an explanation ----------------------------------------------------------------------


def test_an_explanation_is_made_checked_cached_and_counted(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    r = ask(client, gid)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ai" and body["cached"] is False and body["ply"] == 1
    assert "a3" in body["text"] and body["model"] == "fake-model" and body["remaining_today"] == 29

    again = ask(client, gid).json()
    assert again["cached"] is True and again["remaining_today"] == 29 and again["text"] == body["text"]
    assert len(FakeClient.seen) == 1  # the second request never reached the model
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(MoveExplanation)) == 1
        usage = db.scalar(select(LlmUsage))
        assert (usage.outcome, usage.tokens_in, usage.tokens_out) == ("valid", 120, 30)

    listed = client.get(f"/api/games/{gid}/explanations").json()
    assert [i["ply"] for i in listed["items"]] == [1] and listed["remaining_today"] == 29


def test_the_request_to_the_model_holds_no_names_or_headers(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    ask(client, gid)
    sent = json.dumps(FakeClient.seen[0])
    for private in ("Alice", "Bob", "Casual", "Event", "1-0"):
        assert private not in sent, private
    assert "allowed_moves" in sent and "engine_lines" in sent


def test_a_model_that_invents_moves_gets_the_plain_fallback(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    FakeClient.replies = [INVENTED, INVENTED]
    body = ask(client, gid).json()
    assert body["source"] == "fallback" and "Qh5" not in body["text"]
    assert "You played a3." in body["text"] and "e4" in body["text"]
    assert len(FakeClient.seen) == 2  # one retry, told what was wrong
    assert "Qh5" in FakeClient.seen[1][-1]["content"]
    with db_factory() as db:
        assert db.scalar(select(LlmUsage.outcome)) == "fallback"


def test_one_bad_reply_is_retried(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    FakeClient.replies = [INVENTED, GOOD]
    body = ask(client, gid).json()
    assert body["source"] == "ai"
    with db_factory() as db:
        assert db.scalar(select(LlmUsage.outcome)) == "retried"


def test_an_outage_is_reported_and_does_not_use_up_the_allowance(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    FakeClient.error = LlmUnavailable("The explanation model could not be reached.", 502)
    r = ask(client, gid)
    assert r.status_code == 502 and "could not be reached" in r.json()["detail"]
    FakeClient.error = None
    ok = ask(client, gid)
    assert ok.status_code == 200 and ok.json()["remaining_today"] == 29  # the failure did not count
    with db_factory() as db:
        assert sorted(db.scalars(select(LlmUsage.outcome))) == ["failed", "valid"]
        assert db.scalar(select(func.count()).select_from(MoveExplanation)) == 1  # nothing stored for the failure


def test_rate_limited_by_the_provider_passes_retry_after_on(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    FakeClient.error = LlmUnavailable("busy", 429, 42)
    r = ask(client, gid)
    assert r.status_code == 429 and r.headers["retry-after"] == "42"


def test_level_changes_the_cache_and_the_list(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    ask(client, gid)
    opt_in(client, explain_level="beginner")
    assert client.get(f"/api/games/{gid}/explanations").json()["items"] == []
    body = ask(client, gid).json()
    assert body["level"] == "beginner" and body["cached"] is False
    assert "beginner" in json.dumps(FakeClient.seen[-1])


# ---- not possible ----------------------------------------------------------------------------


def test_unanalyzed_games_and_unanalyzed_moves(client, db_factory):
    gid = reviewed_game(client, db_factory)
    plain = client.post("/api/imports/pgn", json={"pgn_text": GAME.replace("Alice", "Zed")}).json()["imported"][0]["id"]
    opt_in(client)
    assert ask(client, plain).status_code == 409
    assert ask(client, gid, 0).status_code == 422 and ask(client, gid, 99).status_code == 422


def test_other_peoples_games_are_invisible(client, make_client, db_factory):
    gid = reviewed_game(client, db_factory)
    other = make_client()
    opt_in(other)
    assert ask(other, gid).status_code == 404
    assert other.get(f"/api/games/{gid}/explanations").status_code == 404


# ---- limits ----------------------------------------------------------------------------------


def test_the_daily_limit_stops_new_explanations_but_not_cached_ones(client, db_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "explain_daily_limit_per_user", 1)
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    assert ask(client, gid, 1).status_code == 200
    limited = ask(client, gid, 3)
    assert limited.status_code == 429 and "today's 1 explanations" in limited.json()["detail"]
    assert ask(client, gid, 1).json()["cached"] is True  # already made: still readable
    assert client.get(f"/api/games/{gid}/explanations").json()["remaining_today"] == 0


def test_the_server_wide_rate_limit_slows_a_burst(client, db_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_requests_per_minute", 1)
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    assert ask(client, gid, 1).status_code == 200
    r = ask(client, gid, 3)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_the_allowance_belongs_to_the_invite_not_the_browser(make_client, db_factory, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "explain_daily_limit_per_user", 1)
    monkeypatch.setattr(s, "access_required", True)
    with db_factory() as db:
        _, code = create_invite(db, "Alice")
        _, other_code = create_invite(db, "Cara")
    a, b, c = make_client(), make_client(), make_client()
    for browser, secret in ((a, code), (b, code), (c, other_code)):
        assert browser.post("/api/access", json={"code": secret}).status_code == 200
        opt_in(browser)
    ga, gb, gc = (reviewed_game(x, db_factory, white=n) for x, n in ((a, "A"), (b, "B"), (c, "C")))
    assert ask(a, ga).status_code == 200
    assert ask(b, gb).status_code == 429  # same friend, second browser: shared allowance
    assert ask(c, gc).status_code == 200  # a different friend has their own


def test_deleting_the_game_removes_its_explanations(client, db_factory):
    gid = reviewed_game(client, db_factory)
    opt_in(client)
    ask(client, gid)
    client.delete(f"/api/games/{gid}")
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(MoveExplanation)) == 0
