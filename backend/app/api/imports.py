from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.models.user import User
from app.schemas.games import (
    DuplicateOut,
    ImportErrorOut,
    ImportResult,
    PgnImportRequest,
)
from app.services import games as games_svc
from app.services.importing.pgn import MAX_PGN_BYTES, ImportLimitError, parse_pgn
from app.services.importing.service import ImportReport, save_games

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _respond(db: Session, report: ImportReport) -> JSONResponse | ImportResult:
    dup_outs = games_svc.to_game_out(db, [g for _, g in report.duplicates])
    result = ImportResult(
        imported=games_svc.to_game_out(db, report.imported),
        duplicates=[
            DuplicateOut(index=i, game=out)
            for (i, _), out in zip(report.duplicates, dup_outs, strict=True)
        ],
        errors=[ImportErrorOut(index=e.index, message=e.message) for e in report.errors],
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
    return _respond(db, save_games(db, user.id, parsed, source="pgn"))


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
