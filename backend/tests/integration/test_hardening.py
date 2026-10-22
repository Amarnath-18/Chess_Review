"""Release hardening: response headers, request-size limit, per-user cap, session throttle."""
import pytest

from app.config import get_settings
from app.services.ratelimit import new_sessions

GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "{white}"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""


def add(client, white):
    return client.post("/api/imports/pgn", json={"pgn_text": GAME.format(white=white)})


# ---- response headers -------------------------------------------------------------------------


def test_every_api_response_carries_the_security_headers(client):
    gid = add(client, "Alice").json()["imported"][0]["id"]
    for r in (
        client.get("/api/games"),
        client.get(f"/api/games/{gid}"),
        client.get(f"/api/games/{gid}/pgn"),
        client.get("/api/healthz"),
        client.get("/api/games/00000000-0000-0000-0000-000000000000"),  # 404
        client.post("/api/imports/pgn", json={"pgn_text": ""}),  # 422
    ):
        h = r.headers
        assert h["x-content-type-options"] == "nosniff", r.url
        assert h["x-frame-options"] == "DENY", r.url
        assert h["referrer-policy"] == "no-referrer", r.url
        assert h["cache-control"] == "no-store", r.url


def test_headers_are_also_on_refusals(make_client):
    c = make_client(start_session=False)
    for r in (c.get("/api/games"), c.post("/api/session", headers={"X-Requested-With": ""})):
        assert r.headers["x-content-type-options"] == "nosniff"


# ---- request size ---------------------------------------------------------------------------------


def test_an_oversized_body_is_refused_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 2000)
    r = client.post("/api/imports/pgn", json={"pgn_text": "x" * 5000})
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    assert client.get("/api/games").json()["total"] == 0


def test_a_body_within_the_limit_is_fine(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 2000)
    assert add(client, "Alice").status_code == 200


def test_the_limit_applies_to_uploads_too(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 2000)
    big = ("x" * 5000).encode()
    r = client.post("/api/imports/pgn/upload", files={"file": ("g.pgn", big, "text/plain")})
    assert r.status_code == 413


def test_reads_are_never_limited(client, monkeypatch):
    add(client, "Alice")
    monkeypatch.setattr(get_settings(), "max_request_bytes", 10)
    assert client.get("/api/games").status_code == 200


def test_a_streamed_body_without_a_length_is_cut_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 2000)

    def chunks():
        for _ in range(50):
            yield b'{"pgn_text": "' + b"x" * 200 if _ == 0 else b"x" * 200

    r = client.post(
        "/api/imports/pgn", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert r.status_code in (400, 413)  # refused, and never turned into a game
    assert client.get("/api/games").json()["total"] == 0


def test_the_default_limit_still_allows_a_full_size_pgn_paste(client):
    """The documented 1 MB PGN limit must not be tripped by JSON overhead."""
    body = {"pgn_text": " " * 1_000_000}
    r = client.post("/api/imports/pgn", json=body)
    assert r.status_code != 413  # (blank text is then refused as "no PGN", a normal 422)


# ---- per-user game cap -------------------------------------------------------------------------------


def test_a_full_history_stops_new_games_but_not_duplicates(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_games_per_user", 2)
    assert add(client, "A").status_code == 200
    assert add(client, "B").status_code == 200

    r = add(client, "C")
    assert r.status_code == 422 and "history is full (2 games)" in r.json()["detail"]
    again = add(client, "A")  # already saved, so it never counts against the limit
    assert again.status_code == 200 and len(again.json()["duplicates"]) == 1
    assert client.get("/api/games").json()["total"] == 2


def test_the_cap_applies_within_one_import(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_games_per_user", 2)
    text = "\n".join(GAME.format(white=n) for n in ("A", "B", "C", "D"))
    body = client.post("/api/imports/pgn", json={"pgn_text": text}).json()
    assert len(body["imported"]) == 2
    assert [e["index"] for e in body["errors"]] == [3, 4]
    assert all("history is full" in e["message"] for e in body["errors"])


def test_deleting_makes_room_again(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_games_per_user", 1)
    gid = add(client, "A").json()["imported"][0]["id"]
    assert add(client, "B").status_code == 422
    client.delete(f"/api/games/{gid}")
    assert add(client, "B").status_code == 200


def test_the_cap_is_per_user(make_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_games_per_user", 1)
    a, b = make_client(), make_client()
    assert add(a, "A").status_code == 200
    assert add(a, "B").status_code == 422
    assert add(b, "B").status_code == 200


# ---- session creation throttle -------------------------------------------------------------------------


@pytest.fixture
def throttled(monkeypatch):
    new_sessions.clear()
    monkeypatch.setattr(get_settings(), "sessions_per_ip_per_hour", 2)
    yield
    new_sessions.clear()


def test_new_sessions_per_address_can_be_limited(make_client, throttled):
    make_client()
    make_client()
    c = make_client(start_session=False)
    r = c.post("/api/session")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0 and "Too many new sessions" in r.json()["detail"]


def test_people_who_already_have_a_session_are_unaffected(make_client, throttled):
    a = make_client()
    make_client()  # the allowance is now used up
    for _ in range(5):
        assert a.post("/api/session").json()["new"] is False
    assert a.get("/api/games").status_code == 200


def test_no_limit_by_default(make_client):
    new_sessions.clear()
    assert get_settings().sessions_per_ip_per_hour == 0
    for _ in range(5):
        make_client()
