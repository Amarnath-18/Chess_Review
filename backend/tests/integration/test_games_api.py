"""API tests: AT-01 (valid PGN), AT-02 (malformed), AT-09 (duplicates), AT-12 (isolation)."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).parent.parent / "fixtures"
GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[WhiteElo "1500"]
[BlackElo "1480"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""


def import_text(client, text=GAME):
    return client.post("/api/imports/pgn", json={"pgn_text": text})


# ---- sessions & CSRF ---------------------------------------------------------


def test_session_is_idempotent_and_sets_hardened_cookie(make_client):
    c = make_client(start_session=False)
    r = c.post("/api/session")
    assert r.status_code == 200 and r.json()["new"] is True
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    again = c.post("/api/session")
    assert again.json()["new"] is False
    assert again.json()["user_id"] == r.json()["user_id"]


def test_endpoints_require_a_session(make_client):
    c = make_client(start_session=False)
    assert c.get("/api/games").status_code == 401
    assert import_text(c).status_code == 401
    assert c.get(f"/api/games/{uuid.uuid4()}").status_code == 401


def test_a_forged_cookie_is_rejected(make_client):
    c = make_client(start_session=False)
    c.cookies.set("sid", "not-a-real-token")
    assert c.get("/api/games").status_code == 401


def test_mutating_requests_without_the_csrf_header_are_refused(client):
    bare = TestClient(app)  # no X-Requested-With
    bare.cookies.update(client.cookies)
    assert bare.post("/api/imports/pgn", json={"pgn_text": GAME}).status_code == 403
    assert bare.post("/api/session").status_code == 403


# ---- AT-01: valid PGN ---------------------------------------------------------


def test_import_valid_pgn_then_list_and_open(client):
    r = import_text(client)
    assert r.status_code == 200
    body = r.json()
    assert len(body["imported"]) == 1 and not body["duplicates"] and not body["errors"]
    game = body["imported"][0]
    assert game["white"] == "Alice" and game["white_elo"] == 1500 and game["ply_count"] == 6
    assert game["played_at"] == "2024-03-09" and game["analysis_status"] == "none"

    listing = client.get("/api/games").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == game["id"]

    detail = client.get(f"/api/games/{game['id']}").json()
    assert [m["san"] for m in detail["moves"]] == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]
    assert detail["moves"][0]["fen"].startswith("rnbqkbnr/pppppppp/8/8/4P3/")
    assert "1. e4 e5" in detail["pgn"]


def test_upload_pgn_file(client):
    data = (FIXTURES / "short_game.pgn").read_bytes()
    r = client.post("/api/imports/pgn/upload", files={"file": ("g.pgn", data, "text/plain")})
    assert r.status_code == 200 and len(r.json()["imported"]) == 1


def test_upload_too_large_is_413(client):
    big = b"x" * 1_000_001
    r = client.post("/api/imports/pgn/upload", files={"file": ("big.pgn", big, "text/plain")})
    assert r.status_code == 413


def test_upload_non_utf8_is_a_clean_422(client):
    r = client.post("/api/imports/pgn/upload", files={"file": ("g.pgn", b"\xff\xfe\x00bad", "x")})
    assert r.status_code == 422 and "UTF-8" in r.json()["detail"]


# ---- AT-02: malformed PGN ------------------------------------------------------


def test_illegal_move_gives_a_clear_422(client):
    r = import_text(client, GAME.replace("2. Nf3", "2. Ke3"))
    assert r.status_code == 422
    body = r.json()
    assert "Ke3" in body["detail"] and body["errors"][0]["index"] == 1
    assert client.get("/api/games").json()["total"] == 0  # nothing saved


@pytest.mark.parametrize("text", ["", "   ", "garbage in, garbage out"])
def test_empty_or_garbage_input_is_422(client, text):
    assert import_text(client, text).status_code == 422


def test_partial_success_reports_per_game_errors(client):
    text = GAME + "\n" + GAME.replace("2. Nf3", "2. Ke3") + "\n" + GAME.replace("Alice", "Carol")
    r = import_text(client, text)
    assert r.status_code == 200
    body = r.json()
    assert len(body["imported"]) == 2 and [e["index"] for e in body["errors"]] == [2]


def test_too_many_games_is_422(client):
    r = import_text(client, GAME * 51)
    assert r.status_code == 422 and "Too many games" in r.json()["detail"]


# ---- AT-09: duplicates ---------------------------------------------------------


def test_reimport_does_not_create_a_duplicate(client):
    first = import_text(client).json()["imported"][0]
    r = import_text(client)
    assert r.status_code == 200
    body = r.json()
    assert not body["imported"] and body["duplicates"][0]["game"]["id"] == first["id"]
    assert client.get("/api/games").json()["total"] == 1


def test_same_game_twice_in_one_file_is_stored_once(client):
    body = import_text(client, GAME + "\n" + GAME).json()
    assert len(body["imported"]) == 1 and len(body["duplicates"]) == 1


def test_different_users_may_import_the_same_game(make_client):
    a, b = make_client(), make_client()
    assert len(import_text(a).json()["imported"]) == 1
    assert len(import_text(b).json()["imported"]) == 1


# ---- AT-12: access control ------------------------------------------------------


def test_other_users_games_are_invisible(make_client):
    a, b = make_client(), make_client()
    gid = import_text(a).json()["imported"][0]["id"]

    assert b.get("/api/games").json()["total"] == 0
    assert b.get(f"/api/games/{gid}").status_code == 404
    assert b.delete(f"/api/games/{gid}").status_code == 404
    # Failed attempts must not have affected the owner's data.
    assert a.get(f"/api/games/{gid}").status_code == 200


def test_unknown_and_foreign_ids_are_indistinguishable(make_client):
    a, b = make_client(), make_client()
    gid = import_text(a).json()["imported"][0]["id"]
    foreign = b.get(f"/api/games/{gid}")
    missing = b.get(f"/api/games/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_malformed_id_is_422_not_500(client):
    assert client.get("/api/games/not-a-uuid").status_code == 422


# ---- deletion, filters, pagination ------------------------------------------------


def test_delete_game(client):
    gid = import_text(client).json()["imported"][0]["id"]
    assert client.delete(f"/api/games/{gid}").status_code == 204
    assert client.get(f"/api/games/{gid}").status_code == 404
    assert client.get("/api/games").json()["total"] == 0


def test_filters_and_pagination(client):
    games = [
        GAME.replace("Alice", name).replace("1-0", res).replace("2024.03.09", date)
        for name, res, date in [
            ("Alice", "1-0", "2024.03.09"),
            ("Carol", "0-1", "2024.04.01"),
            ("Dave_x", "1/2-1/2", "2023.01.15"),
        ]
    ]
    for g in games:
        import_text(client, g.replace("1. e4 e5", f"1. e4 e5 {{{g[:5]}}}", 1))

    assert client.get("/api/games?q=carol").json()["total"] == 1
    assert client.get("/api/games?q=dave_x").json()["total"] == 1
    assert client.get("/api/games?q=%25").json()["total"] == 0  # "%" is literal, not a wildcard
    assert client.get("/api/games?result=0-1").json()["total"] == 1
    assert client.get("/api/games?source=lichess").json()["total"] == 0
    assert client.get("/api/games?date_from=2024-01-01").json()["total"] == 2

    page = client.get("/api/games?page_size=2&page=2").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    newest_first = [g["played_at"] for g in client.get("/api/games").json()["items"]]
    assert newest_first == sorted(newest_first, reverse=True)

    assert client.get("/api/games?page_size=1000").status_code == 422
