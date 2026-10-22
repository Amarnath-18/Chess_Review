"""AT-07 / AT-08 against the REAL Chess.com and Lichess APIs.

Skipped unless RUN_LIVE=1, because they need internet and depend on public accounts:
    docker compose run --rm -e RUN_LIVE=1 worker python -m pytest -q tests/live
"""
import os

import pytest

from app.config import get_settings
from app.services.importing import external

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to run")

CHESSCOM_USER = "hikaru"
LICHESS_USER = "DrNykterstein"


@pytest.fixture(autouse=True)
def _pacing(monkeypatch):
    monkeypatch.setattr(get_settings(), "external_user_cooldown_seconds", 0.0)
    external.preview_cache.clear()
    external.cooldown._last.clear()


def search(client, source, user, n=3):
    r = client.post(
        "/api/imports/preview", json={"source": source, "username": user, "max_games": n}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_at07_import_a_public_chesscom_game(client):
    found = search(client, "chesscom", CHESSCOM_USER)
    games = [g for g in found["games"] if g["importable"]]
    assert games, found
    g = games[0]
    assert g["white"] and g["black"] and g["result"] in ("1-0", "0-1", "1/2-1/2")
    assert g["played_at"] and g["ply_count"] and g["white_elo"]

    r = client.post(
        "/api/imports/commit",
        json={"source": "chesscom", "username": CHESSCOM_USER, "external_ids": [g["external_id"]]},
    )
    assert r.status_code == 200, r.text
    saved = r.json()["imported"][0]
    detail = client.get(f"/api/games/{saved['id']}").json()
    assert detail["source"] == "chesscom" and len(detail["moves"]) == g["ply_count"]

    # the same game again, by its link + a player name: recognised, not duplicated
    again = client.post(
        "/api/imports/url", json={"url": g["url"], "username_hint": CHESSCOM_USER}
    )
    assert again.status_code == 200, again.text
    assert not again.json()["imported"] and len(again.json()["duplicates"]) == 1


def test_at08_import_a_public_lichess_game(client):
    found = search(client, "lichess", LICHESS_USER, 2)
    games = [g for g in found["games"] if g["importable"]]
    assert games, found
    g = games[0]
    assert g["opening_name"] and g["white_elo"] and g["url"].startswith("https://lichess.org/")

    r = client.post(
        "/api/imports/commit",
        json={"source": "lichess", "username": LICHESS_USER, "external_ids": [g["external_id"]]},
    )
    assert r.status_code == 200, r.text
    saved = r.json()["imported"][0]
    detail = client.get(f"/api/games/{saved['id']}").json()
    assert detail["source"] == "lichess" and detail["moves"]

    again = client.post("/api/imports/url", json={"url": g["url"]})
    assert again.status_code == 200, again.text
    assert not again.json()["imported"] and len(again.json()["duplicates"]) == 1


def test_unknown_accounts_give_clear_not_found_errors(client):
    r = client.post(
        "/api/imports/preview",
        json={"source": "chesscom", "username": "zz-no-such-user-9q8w", "max_games": 3},
    )
    assert r.status_code == 404 and "not found" in r.json()["detail"]
    r = client.post(
        "/api/imports/preview",
        json={"source": "lichess", "username": "zz-no-such-user-9q8w", "max_games": 3},
    )
    assert r.status_code == 404 and "not found" in r.json()["detail"]
