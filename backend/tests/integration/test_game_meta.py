"""Favourites, notes and tags (M9.4)."""
import io

import chess.pgn

GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""


def make_game(client, text=GAME) -> str:
    return client.post("/api/imports/pgn", json={"pgn_text": text}).json()["imported"][0]["id"]


def test_new_games_have_no_marks(client):
    gid = make_game(client)
    d = client.get(f"/api/games/{gid}").json()
    assert d["favorite"] is False and d["tags"] == [] and d["has_note"] is False
    assert d["note"] is None and d["move_notes"] == {}


def test_favourite_note_and_tags_are_saved_and_listed(client):
    gid = make_game(client)
    r = client.patch(
        f"/api/games/{gid}",
        json={"favorite": True, "note": "  Lost the thread after move 3.  ", "tags": ["Italian", " endgame  to study", "italian"]},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["favorite"] is True and d["note"] == "Lost the thread after move 3."
    assert d["tags"] == ["endgame to study", "italian"]  # trimmed, lower-cased, de-duplicated, sorted

    item = client.get("/api/games").json()["items"][0]
    assert item["favorite"] is True and item["has_note"] is True and item["tags"] == d["tags"]

    # sending only one field leaves the others alone
    d2 = client.patch(f"/api/games/{gid}", json={"favorite": False}).json()
    assert d2["favorite"] is False and d2["note"] and d2["tags"] == d["tags"]
    # an empty note clears it; an empty list clears the tags
    d3 = client.patch(f"/api/games/{gid}", json={"note": "   ", "tags": []}).json()
    assert d3["note"] is None and d3["tags"] == [] and d3["has_note"] is False


def test_validation(client):
    gid = make_game(client)
    bad = lambda body: client.patch(f"/api/games/{gid}", json=body).status_code  # noqa: E731
    assert bad({"note": "x" * 5001}) == 422
    assert bad({"tags": [""]}) == 422
    assert bad({"tags": ["x" * 31]}) == 422
    assert bad({"tags": [f"t{i}" for i in range(21)]}) == 422
    assert bad({"favorite": "maybe"}) == 422
    assert bad({"unknown": 1}) == 422
    # nothing was half-applied by the failures
    d = client.get(f"/api/games/{gid}").json()
    assert d["tags"] == [] and d["note"] is None


def test_move_notes(client):
    gid = make_game(client)
    r = client.put(f"/api/games/{gid}/notes/3", json={"text": "  Why not d4?  "})
    assert r.status_code == 200 and r.json()["move_notes"] == {"3": "Why not d4?"}
    client.put(f"/api/games/{gid}/notes/5", json={"text": "Bc4 is natural."})
    assert client.get(f"/api/games/{gid}").json()["move_notes"] == {"3": "Why not d4?", "5": "Bc4 is natural."}
    # replace, then remove with empty text
    client.put(f"/api/games/{gid}/notes/3", json={"text": "Better: d4"})
    assert client.get(f"/api/games/{gid}").json()["move_notes"]["3"] == "Better: d4"
    d = client.put(f"/api/games/{gid}/notes/3", json={"text": ""}).json()
    assert list(d["move_notes"]) == ["5"]
    # the move must exist
    assert client.put(f"/api/games/{gid}/notes/0", json={"text": "x"}).status_code == 422
    assert client.put(f"/api/games/{gid}/notes/7", json={"text": "x"}).status_code == 422
    assert client.put(f"/api/games/{gid}/notes/1", json={"text": "x" * 2001}).status_code == 422


def test_filter_by_favourite_and_tag(client):
    a = make_game(client)
    b = make_game(client, GAME.replace("Alice", "Cara"))
    client.patch(f"/api/games/{a}", json={"favorite": True, "tags": ["Italian"]})
    client.patch(f"/api/games/{b}", json={"tags": ["blitz"]})

    ids = lambda q: [g["id"] for g in client.get(f"/api/games?{q}").json()["items"]]  # noqa: E731
    assert ids("favorite=true") == [a]
    assert ids("tag=italian") == [a]
    assert ids("tag=ITALIAN") == [a]  # tags compare ignoring case
    assert ids("tag=blitz") == [b]
    assert ids("tag=nothing") == []
    assert sorted(ids("favorite=false")) == sorted([a, b])  # false means "no filter"
    export = client.get("/api/games/export?tag=italian")
    assert export.status_code == 200 and export.text.count("[Event") == 1


def test_other_users_cannot_see_or_change_them(client, make_client):
    gid = make_game(client)
    client.patch(f"/api/games/{gid}", json={"note": "private", "tags": ["secret"]})
    other = make_client()
    assert other.patch(f"/api/games/{gid}", json={"favorite": True}).status_code == 404
    assert other.put(f"/api/games/{gid}/notes/1", json={"text": "x"}).status_code == 404
    assert other.get("/api/games?tag=secret").json()["total"] == 0


def test_deleting_the_game_removes_its_notes_and_tags(client, db_factory):
    from sqlalchemy import func, select

    from app.models.game import GameMoveNote, GameTag

    gid = make_game(client)
    client.patch(f"/api/games/{gid}", json={"tags": ["a", "b"]})
    client.put(f"/api/games/{gid}/notes/1", json={"text": "n"})
    assert client.delete(f"/api/games/{gid}").status_code == 204
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(GameTag)) == 0
        assert db.scalar(select(func.count()).select_from(GameMoveNote)) == 0


def test_notes_travel_in_the_annotated_export_and_cannot_break_the_pgn():
    from app.services.analysis.annotate import annotate_pgn

    # annotate_pgn does not need a saved review to carry notes
    out = annotate_pgn(
        GAME, [], "Stockfish", None,
        game_note="Played {fast}\nand lost",
        move_notes={3: "Why not d4? } 4. Qh5"},
    )
    game = chess.pgn.read_game(io.StringIO(out))
    assert not game.errors
    assert [n.san() for n in game.mainline()] == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]
    assert "Played [fast] and lost" in game.comment
    assert "Why not d4? ] 4. Qh5" in list(game.mainline())[2].comment
