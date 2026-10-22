"""Fetch games from the public Chess.com and Lichess APIs.

Safety rules (FR-01.10, NFR-03):
- Hosts are fixed in settings. Every URL we request is built here from a validated username or id;
  URLs found inside API responses and user-pasted links are never fetched.
- One request at a time per upstream, with a minimum gap between calls (Lichess asks for this).
- Redirects are not followed; responses are size-capped; every failure becomes an ExternalError
  with a message fit to show the user.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.config import get_settings

LABELS = {"chesscom": "Chess.com", "lichess": "Lichess"}
_CHESSCOM_USER = re.compile(r"^[A-Za-z0-9_-]{3,25}$")
_LICHESS_USER = re.compile(r"^[A-Za-z0-9_-]{2,30}$")
_STANDARD_SPEEDS = "ultraBullet,bullet,blitz,rapid,classical,correspondence"
_URL_SCAN_SECONDS = 45  # wall-clock budget when searching months for a game id


class ExternalError(Exception):
    """A problem with an external source, with an HTTP status and a user-facing message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ExternalGame:
    external_id: str
    pgn: str
    supported: bool = True
    problem: str | None = None  # why it cannot be imported (e.g. a chess variant)
    url: str | None = None


@dataclass
class FetchResult:
    games: list[ExternalGame] = field(default_factory=list)
    skipped_archives: int = 0  # Chess.com months that could not be read
    note: str | None = None


# ---- validation ----------------------------------------------------------------------


def validate_username(source: str, username: str) -> str:
    name = (username or "").strip()
    pattern = _CHESSCOM_USER if source == "chesscom" else _LICHESS_USER
    if not pattern.fullmatch(name):
        raise ExternalError(
            422,
            f"{LABELS[source]} usernames use letters, numbers, '-' and '_' "
            f"({'3-25' if source == 'chesscom' else '2-30'} characters).",
        )
    return name


def parse_game_url(raw: str) -> tuple[str, str]:
    """Return (source, game_id) for a Chess.com or Lichess game link. Only the exact hosts are
    accepted; the link itself is never requested."""
    bad = ExternalError(422, "That link is not a Chess.com or Lichess game link.")
    try:
        u = urlparse((raw or "").strip())
        host = (u.hostname or "").lower()
    except ValueError:
        raise bad from None
    if u.scheme not in ("http", "https") or not host:
        raise bad
    parts = [p for p in u.path.split("/") if p]
    if host == "lichess.org":
        if parts and re.fullmatch(r"[A-Za-z0-9]{8}(?:[A-Za-z0-9]{4})?", parts[0]):
            return "lichess", parts[0][:8]  # a 12-character id is the 8-character game id + player
        raise bad
    if host in ("chess.com", "www.chess.com"):
        m = re.fullmatch(
            r"(?:analysis/)?(?:game/(?:live|daily)|(?:live|daily)/game)/(\d{4,20})", "/".join(parts)
        )
        if m:
            return "chesscom", m[1]
    raise bad


# ---- transport -----------------------------------------------------------------------


class _Throttle:
    """Serialises calls to one upstream and spaces them out."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = 0.0

    @contextmanager
    def slot(self, min_interval: float) -> Iterator[None]:
        with self._lock:
            wait = self._last + min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                yield
            finally:
                self._last = time.monotonic()


_THROTTLES = {"chesscom": _Throttle(), "lichess": _Throttle()}


def make_client() -> httpx.Client:
    """Overridden in tests to inject a mock transport."""
    s = get_settings()
    return httpx.Client(
        timeout=httpx.Timeout(s.external_timeout_seconds),
        headers={"User-Agent": s.external_user_agent},
        follow_redirects=False,
    )


@dataclass
class _Resp:
    status: int
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        import json

        return json.loads(self.body)


def _get(
    client: httpx.Client,
    source: str,
    url: str,
    *,
    params: dict | None = None,
    accept: str = "application/json",
) -> _Resp:
    s = get_settings()
    label = LABELS[source]
    try:
        with _THROTTLES[source].slot(s.external_min_interval_seconds):
            with client.stream("GET", url, params=params, headers={"Accept": accept}) as r:
                chunks: list[bytes] = []
                size = 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > s.external_max_bytes:
                        raise ExternalError(502, f"{label} sent an unexpectedly large response.")
                    chunks.append(chunk)
                return _Resp(r.status_code, b"".join(chunks))
    except httpx.TimeoutException:
        raise ExternalError(502, f"{label} did not respond in time. Please try again.") from None
    except httpx.HTTPError:
        raise ExternalError(502, f"Could not reach {label}. Please try again later.") from None


def _check(resp: _Resp, source: str, not_found: str | None = None) -> None:
    label = LABELS[source]
    if resp.status == 200:
        return
    if resp.status == 429:
        raise ExternalError(
            429, f"{label} is rate limiting requests. Please wait about a minute and try again."
        )
    if resp.status == 404 and not_found:
        raise ExternalError(404, not_found)
    raise ExternalError(502, f"{label} returned an unexpected response ({resp.status}).")


def _json(resp: _Resp, source: str):
    try:
        return resp.json()
    except ValueError:
        raise ExternalError(502, f"{LABELS[source]} sent a response we could not read.") from None


# ---- Chess.com -----------------------------------------------------------------------


def _chesscom_months(client: httpx.Client, user: str) -> list[tuple[int, int]]:
    base = get_settings().chesscom_base_url
    resp = _get(client, "chesscom", f"{base}/pub/player/{user}/games/archives")
    _check(resp, "chesscom", f'Chess.com user "{user}" was not found.')
    data = _json(resp, "chesscom")
    months: list[tuple[int, int]] = []
    for item in data.get("archives", []) if isinstance(data, dict) else []:
        m = re.search(r"/games/(\d{4})/(\d{2})$", str(item))
        if m:  # only the year/month is kept; the URL is rebuilt from the validated username
            months.append((int(m[1]), int(m[2])))
    return sorted(set(months), reverse=True)


def _chesscom_month(client: httpx.Client, user: str, year: int, month: int) -> list[dict] | None:
    """Games of one month, newest first, or None if that month cannot be read."""
    base = get_settings().chesscom_base_url
    resp = _get(client, "chesscom", f"{base}/pub/player/{user}/games/{year:04d}/{month:02d}")
    if resp.status == 429:
        _check(resp, "chesscom")
    if resp.status != 200:
        return None  # real archives sometimes answer 404/5xx; the rest of the history is still good
    try:
        data = resp.json()
    except ValueError:
        return None
    games = data.get("games") if isinstance(data, dict) else None
    if not isinstance(games, list):
        return None
    ok = [g for g in games if isinstance(g, dict)]
    return sorted(ok, key=lambda g: g.get("end_time") or 0, reverse=True)


def _chesscom_game(g: dict) -> ExternalGame | None:
    pgn = g.get("pgn")
    url = str(g.get("url") or "")
    m = re.search(r"/game/(?:live|daily)/(\d+)", url)
    ext_id = m[1] if m else str(g.get("uuid") or "")
    if not pgn or not ext_id:
        return None
    rules = str(g.get("rules") or "chess")
    return ExternalGame(
        external_id=ext_id,
        pgn=str(pgn),
        supported=rules == "chess",
        problem=None
        if rules == "chess"
        else f"{rules} games are not supported (standard chess only)",
        url=url or None,
    )


def fetch_chesscom_games(username: str, max_games: int) -> FetchResult:
    s = get_settings()
    user = validate_username("chesscom", username).lower()
    result = FetchResult()
    seen: set[str] = set()
    scanned = 0
    with make_client() as client:
        months = _chesscom_months(client, user)
        for year, month in months[: s.chesscom_max_archives]:
            scanned += 1
            raw = _chesscom_month(client, user, year, month)
            if raw is None:
                result.skipped_archives += 1
                continue
            for g in raw:
                eg = _chesscom_game(g)
                if eg and eg.external_id not in seen:
                    seen.add(eg.external_id)
                    result.games.append(eg)
                    if len(result.games) >= max_games:
                        return _with_note(result)
    if scanned and result.skipped_archives == scanned:
        raise ExternalError(502, "Chess.com's game archives are unavailable right now. Try later.")
    if not months:
        result.note = f"{user} has no games on Chess.com yet."
    return _with_note(result)


def _with_note(result: FetchResult) -> FetchResult:
    if result.skipped_archives:
        n = result.skipped_archives
        result.note = (
            f"{n} month{'s' if n > 1 else ''} of the archive could not be loaded, so some games "
            "may be missing. Try again later."
        )
    return result


def fetch_chesscom_game(username: str, game_id: str) -> ExternalGame:
    """Chess.com has no lookup by game id, so search the given player's recent months."""
    s = get_settings()
    user = validate_username("chesscom", username).lower()
    unreadable = 0
    deadline = time.monotonic() + _URL_SCAN_SECONDS
    with make_client() as client:
        for year, month in _chesscom_months(client, user)[: s.chesscom_url_scan_archives]:
            if time.monotonic() > deadline:
                break
            raw = _chesscom_month(client, user, year, month)
            if raw is None:
                unreadable += 1
                continue
            for g in raw:
                eg = _chesscom_game(g)
                if eg and eg.external_id == game_id:
                    return eg
    plural = "s" if unreadable > 1 else ""
    extra = f" ({unreadable} month{plural} could not be read.)" if unreadable else ""
    raise ExternalError(
        404,
        f"Game {game_id} was not found in {user}'s recent Chess.com games. Check the username "
        f"(it must be one of the players), or paste the PGN instead.{extra}",
    )


# ---- Lichess -------------------------------------------------------------------------

_LICHESS_ID = re.compile(r'^\[GameId "([A-Za-z0-9]{8})"\]', re.M)
_LICHESS_SITE = re.compile(r'^\[Site "https?://lichess\.org/([A-Za-z0-9]{8})', re.M)
_VARIANT = re.compile(r'^\[Variant "([^"]*)"\]', re.M)


def _lichess_game(chunk: str, base: str) -> ExternalGame | None:
    m = _LICHESS_ID.search(chunk) or _LICHESS_SITE.search(chunk)
    if not m:
        return None
    variant = (_VARIANT.search(chunk) or [None, "Standard"])[1]
    ok = variant in ("Standard", "From Position")
    return ExternalGame(
        external_id=m[1],
        pgn=chunk,
        supported=ok,
        problem=None if ok else f"{variant} games are not supported (standard chess only)",
        url=f"{base}/{m[1]}",
    )


def _split_pgn(text: str) -> list[str]:
    return [c for c in re.split(r"(?:\r?\n){2,}(?=\[Event )", text.strip()) if c.strip()]


_LICHESS_PARAMS = {"opening": "true", "clocks": "false", "evals": "false"}


def fetch_lichess_games(username: str, max_games: int) -> FetchResult:
    base = get_settings().lichess_base_url
    user = validate_username("lichess", username)
    with make_client() as client:
        resp = _get(
            client,
            "lichess",
            f"{base}/api/games/user/{user}",
            params={"max": max_games, "perfType": _STANDARD_SPEEDS, **_LICHESS_PARAMS},
            accept="application/x-chess-pgn",
        )
    _check(resp, "lichess", f'Lichess user "{user}" was not found.')
    games: list[ExternalGame] = []
    seen: set[str] = set()
    for chunk in _split_pgn(resp.text):
        eg = _lichess_game(chunk, base)
        if eg and eg.external_id not in seen:
            seen.add(eg.external_id)
            games.append(eg)
    result = FetchResult(games=games[:max_games])
    if not games:
        result.note = f"No standard-chess games found for {user} on Lichess."
    return result


def fetch_lichess_game(game_id: str) -> ExternalGame:
    base = get_settings().lichess_base_url
    if not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
        raise ExternalError(422, "That is not a valid Lichess game id.")
    with make_client() as client:
        resp = _get(
            client,
            "lichess",
            f"{base}/game/export/{game_id}",
            params=_LICHESS_PARAMS,
            accept="application/x-chess-pgn",
        )
    _check(resp, "lichess", f"Lichess game {game_id} was not found (or it is private).")
    eg = _lichess_game(resp.text.strip(), base)
    if eg is None:
        raise ExternalError(502, "Lichess sent a game we could not read.")
    return eg


def fetch_games(source: str, username: str, max_games: int) -> FetchResult:
    if source == "chesscom":
        return fetch_chesscom_games(username, max_games)
    return fetch_lichess_games(username, max_games)


# ---- per-user pacing and the preview cache -------------------------------------------


class Cooldown:
    """Stops one session from hammering the upstream through us."""

    def __init__(self) -> None:
        self._last: dict[object, float] = {}
        self._lock = threading.Lock()

    def check(self, key: object, seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < seconds:
                raise ExternalError(429, "Please wait a moment before searching again.")
            self._last[key] = now
            if len(self._last) > 1000:  # keep memory bounded
                for k, _ in sorted(self._last.items(), key=lambda kv: kv[1])[:500]:
                    self._last.pop(k, None)


class PreviewCache:
    """Remembers what a recent search returned, so importing the picked games does not need a
    second round trip. A miss just means we fetch again."""

    def __init__(self, max_entries: int = 100) -> None:
        self._data: dict[tuple, tuple[float, FetchResult]] = {}
        self._max = max_entries
        self._lock = threading.Lock()

    def get(self, key: tuple, ttl: float) -> FetchResult | None:
        with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] <= ttl:
                return hit[1]
            self._data.pop(key, None)
            return None

    def put(self, key: tuple, value: FetchResult) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            while len(self._data) > self._max:
                self._data.pop(min(self._data, key=lambda k: self._data[k][0]))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cooldown = Cooldown()
preview_cache = PreviewCache()
