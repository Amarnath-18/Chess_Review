"""Preview / commit / link import on top of the external fetchers."""
from __future__ import annotations

import dataclasses
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

import chess.pgn
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.game import Game
from app.services.importing import external
from app.services.importing.external import ExternalError, ExternalGame, FetchResult
from app.services.importing.pgn import (
    ImportLimitError,
    ParsedGame,
    ParseFailure,
    opening_from_eco_url,
    parse_pgn,
)
from app.services.importing.service import ImportReport, save_games

_PREFIX = re.compile(r"^Game \d+: ")


@dataclass
class PreviewGame:
    external_id: str
    url: str | None
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    played_at: date | None
    time_control: str | None
    opening_name: str | None
    ply_count: int | None
    already_imported: bool
    importable: bool
    problem: str | None


@dataclass
class PreviewData:
    source: str
    username: str
    games: list[PreviewGame] = field(default_factory=list)
    skipped_archives: int = 0
    note: str | None = None


def _parse_single(eg: ExternalGame) -> ParsedGame | ParseFailure:
    try:
        items = parse_pgn(eg.pgn, max_games=1)
    except ImportLimitError as exc:
        return ParseFailure(1, str(exc))
    return items[0]


def _headers(pgn: str) -> dict[str, str]:
    try:
        return dict(chess.pgn.read_headers(io.StringIO(pgn)) or {})
    except Exception:  # headers are only for display; never fail the preview over them
        return {}


def _existing_markers(
    db: Session, owner_id: uuid.UUID, source: str, ids: list[str], fps: list[str]
) -> tuple[set[str], set[str]]:
    """External ids and fingerprints the owner already has."""
    if not ids and not fps:
        return set(), set()
    rows = db.execute(
        select(Game.external_id, Game.fingerprint).where(
            Game.owner_id == owner_id,
            or_(
                (Game.source == source) & Game.external_id.in_(ids or [""]),
                Game.fingerprint.in_(fps or [""]),
            ),
        )
    ).all()
    return {r[0] for r in rows if r[0]}, {r[1] for r in rows}


def _preview_game(eg: ExternalGame, parsed: ParsedGame | ParseFailure) -> PreviewGame:
    if isinstance(parsed, ParsedGame):
        return PreviewGame(
            external_id=eg.external_id,
            url=eg.url,
            white=parsed.white,
            black=parsed.black,
            white_elo=parsed.white_elo,
            black_elo=parsed.black_elo,
            result=parsed.result,
            played_at=parsed.played_at,
            time_control=parsed.time_control,
            opening_name=parsed.opening_name,
            ply_count=parsed.ply_count,
            already_imported=False,
            importable=eg.supported,
            problem=eg.problem,
        )
    h = _headers(eg.pgn)
    return PreviewGame(
        external_id=eg.external_id,
        url=eg.url,
        white=h.get("White", "?")[:100],
        black=h.get("Black", "?")[:100],
        white_elo=None,
        black_elo=None,
        result=h.get("Result", "*") if h.get("Result") in ("1-0", "0-1", "1/2-1/2") else "*",
        played_at=None,
        time_control=h.get("TimeControl"),
        opening_name=opening_from_eco_url(h.get("ECOUrl")) or h.get("Opening"),
        ply_count=None,
        already_imported=False,
        importable=False,
        problem=eg.problem or _PREFIX.sub("", parsed.message),
    )


def _cache_key(owner_id: uuid.UUID, source: str, username: str) -> tuple:
    return (owner_id, source, username.lower())


def _fetch(owner_id: uuid.UUID, source: str, username: str, max_games: int) -> FetchResult:
    """Fetch (rate-limited per user) and remember the result for the commit step."""
    s = get_settings()
    external.cooldown.check(owner_id, s.external_user_cooldown_seconds)
    result = external.fetch_games(source, username, max_games)
    external.preview_cache.put(_cache_key(owner_id, source, username), result)
    return result


def preview(
    db: Session, owner_id: uuid.UUID, source: str, username: str, max_games: int
) -> PreviewData:
    username = external.validate_username(source, username)
    max_games = max(1, min(max_games, get_settings().external_max_games))
    fetched = _fetch(owner_id, source, username, max_games)

    parsed = [(eg, _parse_single(eg)) for eg in fetched.games]
    ids = [eg.external_id for eg, _ in parsed]
    fps = [p.fingerprint for _, p in parsed if isinstance(p, ParsedGame)]
    have_ids, have_fps = _existing_markers(db, owner_id, source, ids, fps)

    out = PreviewData(
        source=source,
        username=username,
        skipped_archives=fetched.skipped_archives,
        note=fetched.note,
    )
    for eg, p in parsed:
        pg = _preview_game(eg, p)
        pg.already_imported = eg.external_id in have_ids or (
            isinstance(p, ParsedGame) and p.fingerprint in have_fps
        )
        out.games.append(pg)
    return out


def _save(
    db: Session, owner_id: uuid.UUID, source: str, picked: list[tuple[str, ExternalGame | None]]
) -> ImportReport:
    """Parse the picked games and save them. `picked` keeps the user's order."""
    items: list[ParsedGame | ParseFailure] = []
    ext_ids: dict[int, str] = {}
    for i, (ext_id, eg) in enumerate(picked, start=1):
        if eg is None:
            items.append(
                ParseFailure(i, f"Game {ext_id} is no longer among the latest games. Search again.")
            )
        elif not eg.supported:
            items.append(ParseFailure(i, f"Game {ext_id}: {eg.problem}"))
        else:
            parsed = _parse_single(eg)
            if isinstance(parsed, ParsedGame):
                items.append(dataclasses.replace(parsed, index=i))
                ext_ids[i] = ext_id
            else:
                items.append(ParseFailure(i, f"Game {ext_id}: {_PREFIX.sub('', parsed.message)}"))
    return save_games(db, owner_id, items, source=source, external_ids=ext_ids)


def commit(
    db: Session, owner_id: uuid.UUID, source: str, username: str, external_ids: list[str]
) -> ImportReport:
    s = get_settings()
    username = external.validate_username(source, username)
    wanted = list(dict.fromkeys(external_ids))  # keep order, drop repeats
    if not 1 <= len(wanted) <= s.external_max_games:
        raise ExternalError(422, f"Choose between 1 and {s.external_max_games} games to import.")

    fetched = external.preview_cache.get(
        _cache_key(owner_id, source, username), s.preview_cache_seconds
    )
    if fetched is None:  # expired, or searched on another server process: fetch again
        fetched = _fetch(owner_id, source, username, s.external_max_games)
    by_id = {g.external_id: g for g in fetched.games}
    return _save(db, owner_id, source, [(i, by_id.get(i)) for i in wanted])


def import_from_url(
    db: Session, owner_id: uuid.UUID, url: str, username_hint: str | None
) -> ImportReport:
    source, game_id = external.parse_game_url(url)
    if source == "chesscom" and not (username_hint or "").strip():
        raise ExternalError(
            422,
            "Chess.com doesn't allow looking up a game from its link alone. Enter the Chess.com "
            "username of one of the players, or paste the game's PGN instead.",
        )
    external.cooldown.check(owner_id, get_settings().external_user_cooldown_seconds)
    if source == "lichess":
        eg = external.fetch_lichess_game(game_id)
    else:
        eg = external.fetch_chesscom_game(username_hint or "", game_id)
    return _save(db, owner_id, source, [(game_id, eg)])
