"""Chess.com / Lichess import (AT-07, AT-08), with a mocked upstream.

Every upstream request is checked against the real host, so these tests also prove that nothing
we fetch comes from a user-supplied or response-supplied URL.
"""
import httpx
import pytest

from app.config import get_settings
from app.services.importing import external

MOVES = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 6. cxd4 Bb4+ 7. Nc3 Nxe4 8. O-O"


@pytest.fixture(autouse=True)
def _fast_and_clean(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "external_min_interval_seconds", 0.0)
    monkeypatch.setattr(s, "external_user_cooldown_seconds", 0.0)
    external.preview_cache.clear()
    external.cooldown._last.clear()
    yield
    external.preview_cache.clear()


# ---- builders -----------------------------------------------------------------------------


def make_pgn(white="Alice", black="Bob", date="2026.09.08", result="1-0", **extra):
    headers = {
        "Event": "Live Chess",
        "Site": "Chess.com",
        "Date": date,
        "White": white,
        "Black": black,
        "Result": result,
        "WhiteElo": "1500",
        "BlackElo": "1480",
        "TimeControl": "300",
        **extra,
    }
    head = "\n".join(f'[{k} "{v}"]' for k, v in headers.items())
    return f"{head}\n\n{MOVES} {result}\n"


def cc_game(game_id, white="Alice", black="Bob", end_time=1000, rules="chess", **pgn_extra):
    pgn = make_pgn(white, black, Link=f"https://www.chess.com/game/live/{game_id}", **pgn_extra)
    return {
        "url": f"https://www.chess.com/game/live/{game_id}",
        "pgn": pgn,
        "rules": rules,
        "end_time": end_time,
        "time_control": "300",
    }


class Upstream:
    """A fake Chess.com + Lichess. Records each request and refuses unexpected hosts."""

    def __init__(self):
        self.calls: list[str] = []
        self.cc_user = "hikaru"
        self.cc_months: dict[str, list[dict] | int] = {}  # "2026/09" -> games, or an HTTP status
        self.cc_archives_status = 200
        self.cc_archive_list: list[str] | None = None
        self.li_user = "drnykterstein"
        self.li_pgn = ""
        self.li_status = 200
        self.li_games: dict[str, str] = {}
        self.raise_exc: Exception | None = None
        self.raw_override: tuple[int, bytes] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if self.raise_exc:
            raise self.raise_exc
        host, path = request.url.host, request.url.path
        assert host in ("api.chess.com", "lichess.org"), f"unexpected host {host}"
        assert request.headers["user-agent"].startswith("ChessReviewLab")
        if self.raw_override:
            return httpx.Response(self.raw_override[0], content=self.raw_override[1])

        if host == "api.chess.com":
            prefix = f"/pub/player/{self.cc_user}/games"
            if not path.startswith(prefix):
                return httpx.Response(404, json={"code": 0, "message": "User not found."})
            if path == f"{prefix}/archives":
                if self.cc_archives_status != 200:
                    return httpx.Response(self.cc_archives_status, json={"message": "nope"})
                urls = self.cc_archive_list
                if urls is None:
                    urls = [f"https://api.chess.com{prefix}/{m}" for m in sorted(self.cc_months)]
                return httpx.Response(200, json={"archives": urls})
            month = path[len(prefix) + 1 :]
            data = self.cc_months.get(month)
            if data is None:
                return httpx.Response(404, json={"message": "no such month"})
            if isinstance(data, int):
                return httpx.Response(data, json={"code": 0, "message": "An internal error has occurred."})
            return httpx.Response(200, json={"games": data})

        # lichess
        if path.lower() == f"/api/games/user/{self.li_user}":  # Lichess names are case-insensitive
            assert "perfType" in request.url.params  # variants are excluded upstream
            if self.li_status != 200:
                return httpx.Response(self.li_status, text="<html>nope</html>")
            return httpx.Response(200, text=self.li_pgn, headers={"content-type": "application/x-chess-pgn"})
        if path.startswith("/game/export/"):
            gid = path.rsplit("/", 1)[1]
            if gid in self.li_games:
                return httpx.Response(200, text=self.li_games[gid])
            return httpx.Response(404, text="<html>missing</html>")
        return httpx.Response(404, text="<html>no such user</html>")


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    monkeypatch.setattr(
        external,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(up.handler),
            headers={"User-Agent": "ChessReviewLab/test"},
            follow_redirects=False,
        ),
    )
    return up


def li_pgn(game_id, white="Alice", black="Bob", variant="Standard", date="2026.10.14"):
    return (
        f'[Event "Rated Blitz game"]\n[Site "https://lichess.org/{game_id}"]\n[Date "{date}"]\n'
        f'[White "{white}"]\n[Black "{black}"]\n[Result "1-0"]\n[GameId "{game_id}"]\n'
        f'[WhiteElo "1800"]\n[BlackElo "1790"]\n[Variant "{variant}"]\n[TimeControl "180+0"]\n'
        f'[ECO "C50"]\n[Opening "Italian Game"]\n\n{MOVES} 1-0\n'
    )


def preview(client, source="chesscom", username="hikaru", max_games=20):
    return client.post(
        "/api/imports/preview", json={"source": source, "username": username, "max_games": max_games}
    )


def commit(client, ids, source="chesscom", username="hikaru"):
    return client.post(
        "/api/imports/commit", json={"source": source, "username": username, "external_ids": ids}
    )


# ---- Chess.com: preview ---------------------------------------------------------------------


def test_chesscom_preview_lists_newest_first_with_metadata(client, upstream):
    upstream.cc_months = {
        "2026/08": [cc_game("100", "Old", "Game", end_time=10)],
        "2026/09": [
            cc_game("201", "Alice", "Bob", end_time=500, ECOUrl="https://www.chess.com/openings/Italian-Game-3...Bc5"),
            cc_game("202", "Carol", "Dave", end_time=900),
        ],
    }
    r = preview(client)
    assert r.status_code == 200
    games = r.json()["games"]
    assert [g["external_id"] for g in games] == ["202", "201", "100"]  # newest first, across months
    g = next(x for x in games if x["external_id"] == "201")
    assert (g["white"], g["black"], g["white_elo"], g["black_elo"]) == ("Alice", "Bob", 1500, 1480)
    assert g["result"] == "1-0" and g["played_at"] == "2026-09-08" and g["time_control"] == "300"
    assert g["opening_name"] == "Italian Game"  # derived from ECOUrl, Chess.com has no Opening tag
    assert g["ply_count"] == 15 and g["importable"] and not g["already_imported"]
    assert g["url"] == "https://www.chess.com/game/live/201"
    assert r.json()["skipped_archives"] == 0
    # nothing was saved by looking
    assert client.get("/api/games").json()["total"] == 0


def test_preview_stops_fetching_older_months_once_it_has_enough(client, upstream):
    upstream.cc_months = {
        "2026/07": [cc_game("1")],
        "2026/08": [cc_game("2", "A2")],
        "2026/09": [cc_game("3", "A3"), cc_game("4", "A4", end_time=2000)],
    }
    r = preview(client, max_games=2)
    assert [g["external_id"] for g in r.json()["games"]] == ["4", "3"]
    months_requested = [c for c in upstream.calls if "/games/2026/" in c]
    assert len(months_requested) == 1  # only the newest month was needed


def test_unreadable_months_are_skipped_not_fatal(client, upstream):
    """Real Chess.com sometimes answers 404/500 for a month. The rest must still load."""
    upstream.cc_months = {"2026/08": [cc_game("100")], "2026/09": 500, "2026/10": 404}
    r = preview(client)
    assert r.status_code == 200
    body = r.json()
    assert [g["external_id"] for g in body["games"]] == ["100"]
    assert body["skipped_archives"] == 2
    assert "2 months" in body["note"] and "missing" in body["note"]


def test_all_months_unreadable_is_an_upstream_error(client, upstream):
    upstream.cc_months = {"2026/09": 500, "2026/10": 500}
    r = preview(client)
    assert r.status_code == 502 and "unavailable" in r.json()["detail"]


def test_user_without_games(client, upstream):
    upstream.cc_months = {}
    r = preview(client)
    assert r.status_code == 200 and r.json()["games"] == [] and "no games" in r.json()["note"]


def test_variants_are_listed_but_not_importable(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1", rules="chess960"), cc_game("2", "A2")]}
    games = {g["external_id"]: g for g in preview(client).json()["games"]}
    assert not games["1"]["importable"] and "chess960" in games["1"]["problem"]
    assert games["2"]["importable"]


def test_unreadable_pgn_is_flagged_with_a_reason(client, upstream):
    bad = cc_game("1")
    bad["pgn"] = bad["pgn"].replace("2. Nf3", "2. Ke3")
    upstream.cc_months = {"2026/09": [bad]}
    g = preview(client).json()["games"][0]
    assert not g["importable"] and "Ke3" in g["problem"] and g["white"] == "Alice"


def test_urls_inside_the_archive_list_are_never_requested(client, upstream):
    """Only the year/month is taken from the list; hosts and paths are rebuilt from our own."""
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    upstream.cc_archive_list = [
        "https://evil.example/pub/player/hikaru/games/2026/09",
        "https://api.chess.com/pub/player/other-user/games/2026/09",
        "http://169.254.169.254/latest/meta-data/",
        "https://api.chess.com/pub/player/hikaru/games/2026/09",
    ]
    r = preview(client)
    assert r.status_code == 200 and len(r.json()["games"]) == 1
    assert all(c.startswith("https://api.chess.com/pub/player/hikaru/games/") for c in upstream.calls)


# ---- Chess.com: commit, duplicates --------------------------------------------------------


def test_commit_imports_only_the_picked_games(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1", "A1"), cc_game("2", "A2"), cc_game("3", "A3")]}
    preview(client)
    r = commit(client, ["3", "1"])
    assert r.status_code == 200
    body = r.json()
    assert [g["white"] for g in body["imported"]] == ["A3", "A1"]  # in the order picked
    assert all(g["source"] == "chesscom" for g in body["imported"])
    assert sorted(g["external_id"] for g in body["imported"]) == ["1", "3"]
    assert client.get("/api/games").json()["total"] == 2


def test_committing_twice_does_not_duplicate(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    preview(client)
    first = commit(client, ["1"]).json()
    second = commit(client, ["1"]).json()
    assert len(first["imported"]) == 1 and not second["imported"] and len(second["duplicates"]) == 1
    assert client.get("/api/games").json()["total"] == 1


def test_a_game_already_imported_as_pgn_is_marked_and_not_duplicated(client, upstream):
    """AT-09 across sources: same game, different origin."""
    game = cc_game("1", "Alice", "Bob")
    client.post("/api/imports/pgn", json={"pgn_text": game["pgn"]})
    upstream.cc_months = {"2026/09": [game, cc_game("2", "Carol", "Dave")]}
    games = {g["external_id"]: g for g in preview(client).json()["games"]}
    assert games["1"]["already_imported"] and not games["2"]["already_imported"]
    body = commit(client, ["1", "2"]).json()
    assert len(body["imported"]) == 1 and len(body["duplicates"]) == 1
    assert client.get("/api/games").json()["total"] == 2


def test_preview_marks_games_imported_earlier_through_this_feature(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1"), cc_game("2", "A2")]}
    preview(client)
    commit(client, ["1"])
    games = {g["external_id"]: g for g in preview(client).json()["games"]}
    assert games["1"]["already_imported"] and not games["2"]["already_imported"]


def test_unsupported_and_vanished_games_are_reported_per_game(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1", rules="chess960"), cc_game("2", "A2")]}
    preview(client)
    r = commit(client, ["1", "2", "999"])
    assert r.status_code == 200
    body = r.json()
    assert len(body["imported"]) == 1 and body["imported"][0]["external_id"] == "2"
    messages = {e["index"]: e["message"] for e in body["errors"]}
    assert "chess960" in messages[1] and "no longer among" in messages[3]


def test_commit_of_only_unusable_games_is_a_422(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1", rules="chess960")]}
    preview(client)
    r = commit(client, ["1"])
    assert r.status_code == 422 and "chess960" in r.json()["detail"]


# ---- preview cache ---------------------------------------------------------------------------


def test_commit_reuses_the_search_without_another_round_trip(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    preview(client)
    calls_after_preview = len(upstream.calls)
    commit(client, ["1"])
    assert len(upstream.calls) == calls_after_preview


def test_commit_fetches_again_when_the_cached_search_is_gone(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    preview(client)
    external.preview_cache.clear()  # expiry, or another server process
    n = len(upstream.calls)
    r = commit(client, ["1"])
    assert r.status_code == 200 and len(r.json()["imported"]) == 1
    assert len(upstream.calls) > n


def test_one_users_search_is_never_used_for_another_user(make_client, upstream):
    a, b = make_client(), make_client()
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    preview(a)
    n = len(upstream.calls)
    r = commit(b, ["1"])  # b never searched, so the server must fetch for b
    assert r.status_code == 200 and len(upstream.calls) > n
    assert a.get("/api/games").json()["total"] == 0 and b.get("/api/games").json()["total"] == 1


# ---- Lichess -------------------------------------------------------------------------------------


def test_lichess_preview_and_commit(client, upstream):
    upstream.li_pgn = "\n\n\n".join([li_pgn("abcd1234", "Alice", "Bob"), li_pgn("efgh5678", "Carol", "Dave")])
    r = preview(client, "lichess", "DrNykterstein")
    assert r.status_code == 200
    games = r.json()["games"]
    assert [g["external_id"] for g in games] == ["abcd1234", "efgh5678"]
    assert games[0]["opening_name"] == "Italian Game" and games[0]["white_elo"] == 1800
    assert games[0]["url"] == "https://lichess.org/abcd1234"

    body = commit(client, ["efgh5678"], "lichess", "DrNykterstein").json()
    assert len(body["imported"]) == 1
    g = body["imported"][0]
    assert g["source"] == "lichess" and g["external_id"] == "efgh5678" and g["white"] == "Carol"


def test_lichess_variant_games_are_not_importable(client, upstream):
    upstream.li_pgn = "\n\n\n".join([li_pgn("abcd1234"), li_pgn("efgh5678", "C", "D", variant="Atomic")])
    games = {g["external_id"]: g for g in preview(client, "lichess", "DrNykterstein").json()["games"]}
    assert games["abcd1234"]["importable"]
    assert not games["efgh5678"]["importable"] and "Atomic" in games["efgh5678"]["problem"]


def test_lichess_empty_result(client, upstream):
    upstream.li_pgn = ""
    r = preview(client, "lichess", "DrNykterstein")
    assert r.status_code == 200 and r.json()["games"] == [] and "No standard-chess" in r.json()["note"]


# ---- link import ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        "https://lichess.org/abcd1234",
        "https://lichess.org/abcd1234/black",
        "https://lichess.org/abcd1234wxyz",
    ],
)
def test_import_lichess_link(client, upstream, link):
    upstream.li_games = {"abcd1234": li_pgn("abcd1234", "Alice", "Bob")}
    r = client.post("/api/imports/url", json={"url": link})
    assert r.status_code == 200, r.text
    g = r.json()["imported"][0]
    assert g["source"] == "lichess" and g["external_id"] == "abcd1234" and g["white"] == "Alice"
    # importing the same link again is recognised
    again = client.post("/api/imports/url", json={"url": link}).json()
    assert not again["imported"] and len(again["duplicates"]) == 1


def test_import_chesscom_link_searches_the_given_players_months(client, upstream):
    upstream.cc_months = {
        "2026/08": [cc_game("183193101999")],
        "2026/09": [cc_game("183193105555", "Alice", "Bob")],
        "2026/10": [cc_game("183193101111")],
    }
    r = client.post(
        "/api/imports/url",
        json={"url": "https://www.chess.com/game/live/183193101999", "username_hint": "hikaru"},
    )
    assert r.status_code == 200, r.text
    g = r.json()["imported"][0]
    assert g["source"] == "chesscom" and g["external_id"] == "183193101999"


def test_chesscom_link_needs_a_username(client, upstream):
    r = client.post("/api/imports/url", json={"url": "https://www.chess.com/game/live/183193101999"})
    assert r.status_code == 422 and "username" in r.json()["detail"]
    assert upstream.calls == []


def test_chesscom_link_not_found_for_that_player(client, upstream):
    upstream.cc_months = {"2026/09": [cc_game("183193105555")]}
    r = client.post(
        "/api/imports/url",
        json={"url": "https://www.chess.com/game/live/12345678", "username_hint": "hikaru"},
    )
    assert r.status_code == 404 and "12345678" in r.json()["detail"]


def test_lichess_link_not_found(client, upstream):
    r = client.post("/api/imports/url", json={"url": "https://lichess.org/zzzzzzzz"})
    assert r.status_code == 404 and "not found" in r.json()["detail"]


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.com/game/live/183193101523",
        "https://chess.com.evil.com/game/live/183193101523",
        "https://lichess.org.evil.io/abcd1234",
        "http://169.254.169.254/latest/meta-data/",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "just some text",
    ],
)
def test_other_links_are_refused_without_any_request(client, upstream, link):
    r = client.post("/api/imports/url", json={"url": link, "username_hint": "hikaru"})
    assert r.status_code == 422 and "not a Chess.com or Lichess game link" in r.json()["detail"]
    assert upstream.calls == []


# ---- errors from upstream ----------------------------------------------------------------------


def test_unknown_chesscom_user(client, upstream):
    upstream.cc_archives_status = 404
    r = preview(client)
    assert r.status_code == 404 and 'user "hikaru" was not found' in r.json()["detail"]


def test_unknown_lichess_user_is_not_parsed_as_games(client, upstream):
    r = preview(client, "lichess", "nobody-here")
    assert r.status_code == 404 and "nobody-here" in r.json()["detail"]


@pytest.mark.parametrize("source, user", [("chesscom", "hikaru"), ("lichess", "drnykterstein")])
def test_rate_limited_upstream(client, upstream, source, user):
    upstream.cc_archives_status = 429
    upstream.li_status = 429
    r = preview(client, source, user)
    assert r.status_code == 429 and "rate limiting" in r.json()["detail"]
    assert r.headers["retry-after"] == "60"


@pytest.mark.parametrize("source, user", [("chesscom", "hikaru"), ("lichess", "drnykterstein")])
def test_upstream_server_error(client, upstream, source, user):
    upstream.cc_archives_status = 503
    upstream.li_status = 503
    r = preview(client, source, user)
    assert r.status_code == 502 and "unexpected response (503)" in r.json()["detail"]


def test_upstream_timeout_and_connection_failure(client, upstream):
    upstream.raise_exc = httpx.ReadTimeout("slow")
    r = preview(client)
    assert r.status_code == 502 and "did not respond in time" in r.json()["detail"]
    upstream.raise_exc = httpx.ConnectError("down")
    r = preview(client, "lichess", "drnykterstein")
    assert r.status_code == 502 and "Could not reach Lichess" in r.json()["detail"]


def test_garbage_from_upstream_does_not_crash(client, upstream):
    upstream.raw_override = (200, b"<html>not json</html>")
    r = preview(client)
    assert r.status_code == 502 and "could not read" in r.json()["detail"]


def test_oversized_upstream_response_is_aborted(client, upstream, monkeypatch):
    monkeypatch.setattr(get_settings(), "external_max_bytes", 100)
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    r = preview(client)
    assert r.status_code == 502 and "unexpectedly large" in r.json()["detail"]


def test_redirects_are_not_followed(client, upstream):
    upstream.raw_override = (302, b"")
    r = preview(client)
    assert r.status_code == 502


# ---- validation, pacing, access control ------------------------------------------------------


@pytest.mark.parametrize("name", ["a", "has space", "x" * 26, "../etc/passwd", "user;drop", "ünï"])
def test_bad_chesscom_usernames_are_rejected_before_any_request(client, upstream, name):
    r = preview(client, "chesscom", name)
    assert r.status_code == 422
    assert upstream.calls == []


def test_bad_lichess_usernames_are_rejected_before_any_request(client, upstream):
    for name in ("x", "x" * 31, "a b", "a/b"):
        assert preview(client, "lichess", name).status_code == 422
    assert upstream.calls == []


def test_request_bounds(client, upstream):
    assert preview(client, max_games=0).status_code == 422
    assert preview(client, max_games=51).status_code == 422
    assert client.post("/api/imports/preview", json={"source": "other", "username": "abc"}).status_code == 422
    assert commit(client, []).status_code == 422
    assert commit(client, [str(i) for i in range(51)]).status_code == 422
    assert upstream.calls == []


def test_a_session_cannot_search_in_rapid_succession(client, upstream, monkeypatch):
    monkeypatch.setattr(get_settings(), "external_user_cooldown_seconds", 60.0)
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    assert preview(client).status_code == 200
    r = preview(client)
    assert r.status_code == 429 and "wait a moment" in r.json()["detail"]


def test_the_cooldown_is_per_session(make_client, upstream, monkeypatch):
    monkeypatch.setattr(get_settings(), "external_user_cooldown_seconds", 60.0)
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    a, b = make_client(), make_client()
    assert preview(a).status_code == 200
    assert preview(b).status_code == 200


def test_every_external_endpoint_needs_a_session(make_client, upstream):
    c = make_client(start_session=False)
    assert preview(c).status_code == 401
    assert commit(c, ["1"]).status_code == 401
    assert c.post("/api/imports/url", json={"url": "https://lichess.org/abcd1234"}).status_code == 401
    assert upstream.calls == []


def test_imported_external_games_are_private_to_their_owner(make_client, upstream):
    a, b = make_client(), make_client()
    upstream.cc_months = {"2026/09": [cc_game("1")]}
    preview(a)
    gid = commit(a, ["1"]).json()["imported"][0]["id"]
    assert b.get(f"/api/games/{gid}").status_code == 404
    assert b.get("/api/games").json()["total"] == 0
