"""Favourites, notes and tags: the owner's own annotations on a game."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.game import Game, GameMoveNote, GameTag

MAX_TAGS = 20
MAX_TAG_LENGTH = 30
MAX_NOTE_LENGTH = 5000
MAX_MOVE_NOTE_LENGTH = 2000
MAX_MOVE_NOTES = 200


class MetaError(ValueError):
    pass


def normalize_tag(raw: str) -> str:
    """Trimmed, single-spaced, lower-case; a tag is a short plain label."""
    tag = re.sub(r"\s+", " ", raw).strip().lower()
    if not tag:
        raise MetaError("A tag cannot be empty.")
    if len(tag) > MAX_TAG_LENGTH:
        raise MetaError(f"A tag can be at most {MAX_TAG_LENGTH} characters.")
    if any(not (c.isprintable()) for c in tag):
        raise MetaError("Tags can only contain printable characters.")
    return tag


def normalize_tags(raw: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in raw:
        seen[normalize_tag(item)] = None  # duplicates (ignoring case and spacing) collapse
    tags = list(seen)
    if len(tags) > MAX_TAGS:
        raise MetaError(f"A game can have at most {MAX_TAGS} tags.")
    return sorted(tags)


def tags_for(db: Session, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {gid: [] for gid in game_ids}
    if not game_ids:
        return out
    rows = db.execute(
        select(GameTag.game_id, GameTag.tag)
        .where(GameTag.game_id.in_(game_ids))
        .order_by(GameTag.tag)
    )
    for gid, tag in rows:
        out[gid].append(tag)
    return out


def move_notes_for(db: Session, game_id: uuid.UUID) -> dict[int, str]:
    rows = db.execute(
        select(GameMoveNote.ply, GameMoveNote.text)
        .where(GameMoveNote.game_id == game_id)
        .order_by(GameMoveNote.ply)
    )
    return {ply: text for ply, text in rows}


def set_tags(db: Session, game: Game, tags: list[str]) -> None:
    wanted = normalize_tags(tags)
    db.execute(delete(GameTag).where(GameTag.game_id == game.id))
    db.add_all(GameTag(game_id=game.id, tag=t) for t in wanted)


def set_note(game: Game, note: str | None) -> None:
    cleaned = (note or "").strip()
    if len(cleaned) > MAX_NOTE_LENGTH:
        raise MetaError(f"A note can be at most {MAX_NOTE_LENGTH} characters.")
    game.note = cleaned or None


def set_move_note(db: Session, game: Game, ply: int, text: str) -> None:
    if not 1 <= ply <= game.ply_count:
        raise MetaError(f"This game has moves 1 to {game.ply_count}.")
    cleaned = text.strip()
    if len(cleaned) > MAX_MOVE_NOTE_LENGTH:
        raise MetaError(f"A move note can be at most {MAX_MOVE_NOTE_LENGTH} characters.")
    existing = db.get(GameMoveNote, (game.id, ply))
    if not cleaned:
        if existing is not None:
            db.delete(existing)
        return
    if existing is None:
        count = db.scalar(
            select(func.count()).select_from(GameMoveNote).where(GameMoveNote.game_id == game.id)
        )
        if (count or 0) >= MAX_MOVE_NOTES:
            raise MetaError(f"A game can have at most {MAX_MOVE_NOTES} move notes.")
        db.add(GameMoveNote(game_id=game.id, ply=ply, text=cleaned))
    else:
        existing.text = cleaned
