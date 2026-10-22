"""Who "I" am in a game. There are no accounts, so the person lists their own names (Settings);
the usernames of remembered Chess.com / Lichess accounts count too. A game where neither side
matches, or where both do, cannot be attributed and is left out of personal statistics."""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.game import Game
from app.models.source import LinkedSource
from app.models.user import User

MAX_NAMES = 5
MAX_NAME_LENGTH = 30


def clean_names(raw: list[str]) -> list[str]:
    """Trimmed, de-duplicated (ignoring case) and limited; empty entries are dropped."""
    seen: dict[str, str] = {}
    for item in raw:
        name = " ".join(item.split())
        if not name:
            continue
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"A name can be at most {MAX_NAME_LENGTH} characters.")
        seen.setdefault(name.lower(), name)
    if len(seen) > MAX_NAMES:
        raise ValueError(f"You can list at most {MAX_NAMES} names.")
    return list(seen.values())


def my_names(db: Session, user: User) -> set[str]:
    """Lower-case names that mean this person: their own list plus remembered accounts."""
    names = {n.lower() for n in (user.settings or {}).get("my_names", [])}
    names |= set(
        db.scalars(select(LinkedSource.username_key).where(LinkedSource.owner_id == user.id))
    )
    return names


def my_color(game: Game, names: set[str]) -> str | None:
    """"white" / "black", or None when it cannot be told (no match, or both sides match)."""
    white, black = game.white.lower() in names, game.black.lower() in names
    if white == black:
        return None
    return "white" if white else "black"


def owner_names_for(db: Session, owner_id: uuid.UUID) -> set[str]:
    user = db.get(User, owner_id)
    return my_names(db, user) if user else set()


def invalidate_scans(db: Session, owner_id: uuid.UUID) -> None:
    """The person's names changed, so games must be looked at again for puzzles. Does not commit."""
    db.execute(update(Game).where(Game.owner_id == owner_id).values(puzzles_scanned_run=None))
