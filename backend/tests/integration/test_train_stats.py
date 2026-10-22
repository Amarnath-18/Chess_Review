"""My names, the puzzle trainer and personal statistics (M10)."""
from datetime import timedelta

from sqlalchemy import func, select

from app.models.base import utcnow
from app.models.puzzle import Puzzle, PuzzleAttempt
from tests.helpers import seed_review

GAME = """[Event "Casual"]
[Date "2024.03.09"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[TimeControl "300+0"]

1. a3 e5 2. e4 Nc6 3. Nf3 Bc5 1-0
"""

# White's 1.a3 was a blunder (the engine wanted 1.e4 by a wide margin)
CLEAR = [(300, ["e2e4", "e7e5"]), (0, ["d2d4"]), (-50, ["g1f3"])]
WRONG_FIRST = {0: {"lines": CLEAR}, 1: {"cls": "blunder", "loss": 34.0, "cp": -100}}


def make_game(client, text=GAME, white="Alice") -> str:
    r = client.post("/api/imports/pgn", json={"pgn_text": text.replace("Alice", white)})
    return r.json()["imported"][0]["id"]


def set_names(client, *names):
    r = client.put("/api/settings", json={"my_names": list(names)})
    assert r.status_code == 200
    return r.json()


# ---- 10.0 my names ---------------------------------------------------------------------


def test_my_names_are_saved_cleaned_and_limited(client):
    assert client.get("/api/settings").json()["my_names"] == []
    assert set_names(client, "  Alice ", "alice", "Bobby  Tables", "")["my_names"] == ["Alice", "Bobby Tables"]
    assert client.put("/api/settings", json={"my_names": [f"n{i}" for i in range(6)]}).status_code == 422
    assert client.put("/api/settings", json={"my_names": ["x" * 31]}).status_code == 422
    assert client.put("/api/settings", json={"default_depth": 12}).json()["my_names"] == ["Alice", "Bobby Tables"]
    assert set_names(client)["my_names"] == []


def test_remembered_accounts_count_as_me(client, db_factory):
    gid = make_game(client, white="DrNykterstein")
    seed_review(db_factory, gid, WRONG_FIRST)
    assert client.get("/api/train").json()["needs_names"] is True
    client.post("/api/sources", json={"source": "lichess", "username": "drnykterstein"})
    body = client.get("/api/train").json()
    assert body["needs_names"] is False and body["total"] == 1


# ---- 10.2 puzzles ----------------------------------------------------------------------


def test_nothing_without_names_or_reviews(client):
    body = client.get("/api/train").json()
    assert body["needs_names"] is True and body["next"] is None and body["total"] == 0


def test_my_blunder_becomes_a_puzzle_that_hides_its_answer(client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, WRONG_FIRST)
    set_names(client, "Alice")
    body = client.get("/api/train").json()
    assert body["games_looked_at"] == 1 and body["new_puzzles"] == 1
    assert body["total"] == 1 and body["due"] == 1
    p = body["next"]
    assert p["side_to_move"] == "white" and p["game_id"] == gid and p["ply"] == 1
    assert p["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert set(p) == {"id", "fen", "side_to_move", "game_id", "ply", "box"}  # no solution leaked

    # asking again finds nothing new
    again = client.get("/api/train").json()
    assert again["new_puzzles"] == 0 and again["games_looked_at"] == 0 and again["total"] == 1


def test_only_my_mistakes_and_only_identifiable_games(client, db_factory):
    mine = make_game(client)
    theirs = make_game(client, GAME.replace("Bob", "Cy"), white="Zed")  # neither side is me
    seed_review(db_factory, mine, WRONG_FIRST)
    seed_review(db_factory, theirs, WRONG_FIRST)
    set_names(client, "Bob")  # Bob only played well; his side has no mistakes
    body = client.get("/api/train").json()
    assert body["total"] == 0 and body["next"] is None
    set_names(client, "Alice")  # now White's blunder is mine
    assert client.get("/api/train").json()["total"] == 1  # the earlier scan left it open for later


def test_answering_reschedules_and_reveals(client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, WRONG_FIRST)
    set_names(client, "Alice")
    pid = client.get("/api/train").json()["next"]["id"]

    wrong = client.post(f"/api/train/{pid}/answer", json={"uci": "d2d4"}).json()
    assert wrong["correct"] is False and wrong["box"] == 1
    assert wrong["best_uci"] == "e2e4" and wrong["best_san"] == "e4" and wrong["played_san"] == "a3"
    assert wrong["line_san"][:2] == ["e4", "e5"] and wrong["game_id"] == gid and wrong["ply"] == 1
    assert wrong["due"] == 0  # not due again for ten minutes
    assert client.get("/api/train").json()["next"] is None

    with db_factory() as db:  # time passes: it is due again
        p = db.scalar(select(Puzzle))
        p.due_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/train").json()["next"]["id"] == pid

    right = client.post(f"/api/train/{pid}/answer", json={"uci": "e2e4"}).json()
    assert right["correct"] is True and right["box"] == 2
    with db_factory() as db:
        p = db.scalar(select(Puzzle))
        assert timedelta(hours=23) < p.due_at - utcnow() < timedelta(hours=25)  # a day later
        assert db.scalar(select(func.count()).select_from(PuzzleAttempt)) == 2
    # a miss sends it back to the first box
    with db_factory() as db:
        p = db.scalar(select(Puzzle))
        p.due_at = utcnow()
        db.commit()
    assert client.post(f"/api/train/{pid}/answer", json={"uci": "a2a3"}).json()["box"] == 1


def test_boxes_climb_and_stop_at_five(client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, WRONG_FIRST)
    set_names(client, "Alice")
    pid = client.get("/api/train").json()["next"]["id"]
    boxes = []
    for _ in range(6):
        with db_factory() as db:
            db.scalar(select(Puzzle)).due_at = utcnow()
            db.commit()
        boxes.append(client.post(f"/api/train/{pid}/answer", json={"uci": "e2e4"}).json()["box"])
    assert boxes == [2, 3, 4, 5, 5, 5]
    assert client.get("/api/train").json()["mastered"] == 1


def test_answer_validation_and_ownership(client, make_client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, WRONG_FIRST)
    set_names(client, "Alice")
    pid = client.get("/api/train").json()["next"]["id"]
    assert client.post(f"/api/train/{pid}/answer", json={"uci": "e2e5"}).status_code == 422  # illegal
    assert client.post(f"/api/train/{pid}/answer", json={"uci": "nonsense"}).status_code == 422
    assert client.post(f"/api/train/{pid}/answer", json={"move": "e2e4"}).status_code == 422
    other = make_client()
    assert other.post(f"/api/train/{pid}/answer", json={"uci": "e2e4"}).status_code == 404
    assert other.get("/api/train").json()["total"] == 0
    with db_factory() as db:  # nothing was recorded by the rejected answers
        assert db.scalar(select(func.count()).select_from(PuzzleAttempt)) == 0


def test_deleting_the_game_removes_its_puzzles(client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, WRONG_FIRST)
    set_names(client, "Alice")
    client.get("/api/train")
    client.delete(f"/api/games/{gid}")
    assert client.get("/api/train").json()["total"] == 0


# ---- 10.3 statistics -------------------------------------------------------------------


def test_stats_exclude_games_that_cannot_be_attributed(client, db_factory):
    mine = make_game(client)
    other = make_game(client, GAME.replace("Bob", "Cy"), white="Zed")
    seed_review(db_factory, mine, WRONG_FIRST)
    seed_review(db_factory, other, WRONG_FIRST)
    make_game(client, GAME.replace("Bob", "Di"), white="Eve")  # never analyzed

    s = client.get("/api/stats").json()
    assert s["needs_names"] is True and s["games_included"] == 0 and s["games_analyzed"] == 2

    set_names(client, "Alice")
    s = client.get("/api/stats").json()
    assert s["needs_names"] is False
    assert s["games_analyzed"] == 2 and s["games_included"] == 1 and s["games_unidentified"] == 1
    assert s["overall"]["moves"] == 3 and s["overall"]["blunders"] == 1  # Alice's three moves only
    assert [t["opponent"] for t in s["trend"]] == ["Bob"]


def test_small_samples_are_flagged_and_never_called_weaknesses(client, db_factory):
    gid = make_game(client)
    seed_review(db_factory, gid, {**WRONG_FIRST, 3: {"cls": "good"}, 5: {"cls": "good"}})
    set_names(client, "Alice")
    s = client.get("/api/stats").json()
    assert s["min_moves"] == 30 and s["min_games"] == 10
    assert s["overall"]["moves"] == 3 and s["overall"]["reliable"] is False
    for bucket in s["by_phase"] + s["by_color"] + s["by_time_control"]:
        assert bucket["reliable"] is False and bucket["moves"] < s["min_moves"]
    assert s["highlights"] == []  # no claims from a handful of moves
    assert [b["key"] for b in s["by_color"]] == ["white"]
    assert [b["key"] for b in s["by_time_control"]] == ["blitz"]  # "300+0"
    assert [b["key"] for b in s["by_phase"]] == ["opening"]
    [o] = s["openings"]
    assert o["games"] == 1 and o["reliable"] is False and o["wins"] == 1  # Alice won as White


def test_a_reliable_bucket_needs_enough_moves_and_a_comparison(client, db_factory):
    moves = []
    for _ in range(20):
        moves += ["Nf3", "Nf6", "Ng1", "Ng8"]
    text = (
        '[White "Alice"]\n[Black "Bob"]\n[Result "1/2-1/2"]\n[TimeControl "600+0"]\n\n'
        + " ".join(f"{i // 2 + 1}. {m}" if i % 2 == 0 else m for i, m in enumerate(moves))
        + " 1/2-1/2\n"
    )
    gid = make_game(client, text)
    # Alice (White) plays the odd plies: good for 40 plies, then blunders for the rest
    specs = {ply: {"cls": "blunder", "loss": 25.0} for ply in range(41, 81, 2)}
    specs.update({ply: {"cls": "best"} for ply in range(1, 41, 2)})
    seed_review(db_factory, gid, specs)
    set_names(client, "Alice")
    s = client.get("/api/stats").json()
    phases = {b["key"]: b for b in s["by_phase"]}
    assert phases["opening"]["moves"] == 10 and phases["opening"]["reliable"] is False
    assert phases["middlegame"]["moves"] == 30 and phases["middlegame"]["reliable"] is True
    assert phases["middlegame"]["serious_per_100"] == 66.7  # 20 blunders in 30 moves
    # only one reliable bucket, so there is nothing to compare it with and no claim is made
    assert [h for h in s["highlights"] if h.startswith("Phase")] == []
