import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.base import utcnow
from app.models.source import LinkedSource
from app.models.user import User
from app.schemas.games import PreviewGameOut
from app.schemas.sources import NewGamesOut, SourceCreate, SourceOut
from app.services import identity, user_settings
from app.services.importing import external, external_import
from app.services.importing.external import ExternalError

router = APIRouter(prefix="/api/sources", tags=["sources"])

MAX_SOURCES = 5


def _owned(db: Session, user: User, source_id: uuid.UUID) -> LinkedSource:
    src = db.scalar(
        select(LinkedSource).where(LinkedSource.id == source_id, LinkedSource.owner_id == user.id)
    )
    if src is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return src


@router.get("", response_model=list[SourceOut])
def list_sources(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(LinkedSource)
            .where(LinkedSource.owner_id == user.id)
            .order_by(LinkedSource.created_at)
        )
    )


@router.post("", response_model=SourceOut, status_code=201)
def remember_source(
    body: SourceCreate,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Remember an account. Remembering the same account twice is harmless."""
    try:
        username = external.validate_username(body.source, body.username)
    except ExternalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    key = username.lower()
    existing = db.scalar(
        select(LinkedSource).where(
            LinkedSource.owner_id == user.id,
            LinkedSource.source == body.source,
            LinkedSource.username_key == key,
        )
    )
    if existing is not None:
        response.status_code = 200
        return existing
    count = db.scalar(
        select(func.count()).select_from(LinkedSource).where(LinkedSource.owner_id == user.id)
    )
    if (count or 0) >= MAX_SOURCES:
        raise HTTPException(
            status_code=422, detail=f"You can remember at most {MAX_SOURCES} accounts."
        )
    src = LinkedSource(owner_id=user.id, source=body.source, username=username, username_key=key)
    db.add(src)
    identity.invalidate_scans(db, user.id)
    db.commit()
    return src


@router.delete("/{source_id}", status_code=204)
def forget_source(
    source_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, user, source_id))
    identity.invalidate_scans(db, user.id)
    db.commit()
    return Response(status_code=204)


@router.post("/{source_id}/check", response_model=NewGamesOut)
def check_for_new_games(
    source_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Look at the account's most recent games and list those not saved yet. Nothing is saved:
    import the ones you want with /api/imports/commit (the lookup is remembered for a few minutes).
    It uses the same paced, rate-limited fetchers as a search."""
    src = _owned(db, user, source_id)
    count = user_settings.effective(user)["import_count"]
    try:
        data = external_import.preview(db, user.id, src.source, src.username, count)
    except ExternalError as exc:
        headers = {"Retry-After": "60"} if exc.status_code == 429 else None
        raise HTTPException(status_code=exc.status_code, detail=exc.message, headers=headers) from exc
    src.last_checked_at = utcnow()
    db.commit()
    fresh = [g for g in data.games if not g.already_imported]
    new = [g for g in fresh if g.importable]
    return NewGamesOut(
        source_id=src.id,
        source=src.source,
        username=src.username,
        new_games=[PreviewGameOut(**vars(g)) for g in new],
        checked=len(data.games),
        already_saved=len(data.games) - len(fresh),
        cannot_import=len(fresh) - len(new),
        note=data.note,
        skipped_archives=data.skipped_archives,
    )
