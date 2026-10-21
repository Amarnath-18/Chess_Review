"""Persist parsed games for an owner, skipping duplicates."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.game import Game
from app.services.importing.pgn import ParsedGame, ParseFailure


@dataclass
class ImportReport:
    imported: list[Game] = field(default_factory=list)
    duplicates: list[tuple[int, Game]] = field(default_factory=list)
    errors: list[ParseFailure] = field(default_factory=list)


def _existing(db: Session, owner_id: uuid.UUID, p: ParsedGame, source: str,
              external_id: str | None) -> Game | None:
    stmt = select(Game).where(Game.owner_id == owner_id)
    if external_id is not None:
        cond = (Game.source == source) & (Game.external_id == external_id)
        stmt = stmt.where(cond | (Game.fingerprint == p.fingerprint))
    else:
        stmt = stmt.where(Game.fingerprint == p.fingerprint)
    return db.scalars(stmt.limit(1)).first()


def save_games(
    db: Session,
    owner_id: uuid.UUID,
    parsed: list[ParsedGame | ParseFailure],
    source: str = "pgn",
    external_ids: dict[int, str] | None = None,
) -> ImportReport:
    report = ImportReport()
    for item in parsed:
        if isinstance(item, ParseFailure):
            report.errors.append(item)
            continue
        external_id = (external_ids or {}).get(item.index)
        dup = _existing(db, owner_id, item, source, external_id)
        if dup is not None:
            report.duplicates.append((item.index, dup))
            continue
        game = Game(
            owner_id=owner_id,
            source=source,
            external_id=external_id,
            fingerprint=item.fingerprint,
            pgn=item.pgn,
            white=item.white,
            black=item.black,
            white_elo=item.white_elo,
            black_elo=item.black_elo,
            result=item.result,
            played_at=item.played_at,
            time_control=item.time_control,
            opening_name=item.opening_name,
            eco=item.eco,
            event=item.event,
            ply_count=item.ply_count,
        )
        try:
            with db.begin_nested():
                db.add(game)
        except IntegrityError:
            # A concurrent request inserted the same game between our check and insert.
            existing = _existing(db, owner_id, item, source, external_id)
            if existing is None:
                raise
            report.duplicates.append((item.index, existing))
            continue
        report.imported.append(game)
    db.commit()
    return report
