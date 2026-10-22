from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.user import User
from app.schemas.games import (
    CommitRequest,
    DuplicateOut,
    ImportErrorOut,
    ImportResult,
    PgnImportRequest,
    PreviewGameOut,
    PreviewOut,
    PreviewRequest,
    UrlImportRequest,
)
from app.services import games as games_svc
from app.services.analysis import batches
from app.services.importing import external_import
from app.services.importing.external import ExternalError
from app.services.importing.pgn import MAX_PGN_BYTES, ImportLimitError, parse_pgn
from app.services.importing.service import ImportReport, save_games

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _respond(db: Session, user: User, report: ImportReport) -> JSONResponse | ImportResult:
    dup_outs = games_svc.to_game_out(db, [g for _, g in report.duplicates])
    result = ImportResult(
        imported=games_svc.to_game_out(db, report.imported),
        duplicates=[
            DuplicateOut(index=i, game=out)
            for (i, _), out in zip(report.duplicates, dup_outs, strict=True)
        ],
        errors=[ImportErrorOut(index=e.index, message=e.message) for e in report.errors],
        auto_analyzing=batches.queue_imported(db, user, report.imported),
    )
    if report.errors and not report.imported and not report.duplicates:
        body = result.model_dump(mode="json")
        body["detail"] = report.errors[0].message
        return JSONResponse(body, status_code=422)
    return result


def _import_text(db: Session, user: User, text: str) -> JSONResponse | ImportResult:
    try:
        parsed = parse_pgn(text)
    except ImportLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _respond(db, user, save_games(db, user.id, parsed, source="pgn"))


@router.post("/pgn", response_model=ImportResult, responses={422: {"model": None}})
def import_pgn_text(
    body: PgnImportRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    return _import_text(db, user, body.pgn_text)


@router.post("/pgn/upload", response_model=ImportResult, responses={422: {"model": None}})
def import_pgn_file(
    file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)
):
    raw = file.file.read(MAX_PGN_BYTES + 1)
    if len(raw) > MAX_PGN_BYTES:
        raise HTTPException(status_code=413, detail="PGN file is too large (limit 1 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="The file must be UTF-8 text.") from exc
    return _import_text(db, user, text)


# ---- Chess.com / Lichess ---------------------------------------------------------------


def _http_error(exc: ExternalError) -> HTTPException:
    headers = {"Retry-After": "60"} if exc.status_code == 429 else None
    return HTTPException(status_code=exc.status_code, detail=exc.message, headers=headers)


@router.post("/preview", response_model=PreviewOut)
def preview_external(
    body: PreviewRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Look up a user's recent games on Chess.com or Lichess without saving anything."""
    try:
        data = external_import.preview(db, user.id, body.source, body.username, body.max_games)
    except ExternalError as exc:
        raise _http_error(exc) from exc
    return PreviewOut(
        source=data.source,
        username=data.username,
        games=[PreviewGameOut(**vars(g)) for g in data.games],
        skipped_archives=data.skipped_archives,
        note=data.note,
    )


@router.post("/commit", response_model=ImportResult, responses={422: {"model": None}})
def commit_external(
    body: CommitRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Import the games picked from a preview."""
    try:
        report = external_import.commit(db, user.id, body.source, body.username, body.external_ids)
    except ExternalError as exc:
        raise _http_error(exc) from exc
    return _respond(db, user, report)


@router.post("/url", response_model=ImportResult, responses={422: {"model": None}})
def import_game_link(
    body: UrlImportRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Import one game from a Chess.com or Lichess game link."""
    try:
        report = external_import.import_from_url(db, user.id, body.url, body.username_hint)
    except ExternalError as exc:
        raise _http_error(exc) from exc
    return _respond(db, user, report)
