import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.config import get_settings
from app.models.user import User
from app.schemas.analysis import JobOut
from app.schemas.games import GameDetail, GameList, GameUpdate, MoveNoteUpdate, MoveOut
from app.services import game_meta as meta
from app.services import games as svc
from app.services.analysis.annotate import annotated_pgn_for
from app.services.clocks import game_clocks

router = APIRouter(prefix="/api/games", tags=["games"])

PGN_TYPE = "application/x-chess-pgn"


def _owned(db: Session, user: User, game_id: uuid.UUID):
    game = svc.get_owned_game(db, user.id, game_id)
    if game is None:
        # 404 (not 403) so ids belonging to other users are indistinguishable from missing ones.
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def game_filters(
    q: str | None = Query(None, max_length=100),
    source: Literal["pgn", "chesscom", "lichess"] | None = None,
    result: Literal["1-0", "0-1", "1/2-1/2", "*"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    analyzed: bool | None = None,
    sort: Literal["played", "added"] = "played",
    favorite: bool | None = None,
    tag: str | None = Query(None, max_length=30),
) -> svc.GameFilters:
    return svc.GameFilters(q, source, result, date_from, date_to, analyzed, sort, favorite, tag)


@router.get("", response_model=GameList)
def list_games(
    filters: svc.GameFilters = Depends(game_filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    items, total = svc.list_games(db, user.id, filters, page, page_size)
    return GameList(
        items=svc.to_game_out(db, items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/export")
def export_games(
    filters: svc.GameFilters = Depends(game_filters),
    annotated: bool = Query(False, description="Embed evaluations and move marks in analyzed games"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Download every game matching the filters as one PGN file."""
    limit = get_settings().export_max_games
    total = svc.count_games(db, user.id, filters)
    if total == 0:
        raise HTTPException(status_code=404, detail="No games match; nothing to export.")
    if total > limit:
        raise HTTPException(
            status_code=422,
            detail=f"{total} games match; at most {limit} can be exported at once. Narrow it down.",
        )
    stem = f"chess-review-games{'-annotated' if annotated else ''}-{date.today().isoformat()}"
    name = svc.safe_filename(stem)
    # Built in memory (capped at export_max_games) so the database session is still open while
    # we read; a streamed body could outlive it.
    return Response(
        "".join(svc.iter_pgn(db, user.id, filters, annotated=annotated)),
        media_type=PGN_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Game-Count": str(total),
        },
    )


@router.get("/{game_id}/pgn")
def download_game_pgn(
    game_id: uuid.UUID,
    annotated: bool = Query(False, description="Embed the engine's evaluations and move marks"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    game = _owned(db, user, game_id)
    text = game.pgn.strip() + "\n"
    filename = svc.game_filename(game)
    if annotated:
        text = annotated_pgn_for(db, game)
        if text is None:
            raise HTTPException(
                status_code=409, detail="Analyze this game first to download it with its analysis."
            )
        filename = filename.removesuffix(".pgn") + "-analysis.pgn"
    return Response(
        text,
        media_type=PGN_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{game_id}", response_model=GameDetail)
def get_game(game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _detail(db, _owned(db, user, game_id))


def _detail(db: Session, game) -> GameDetail:
    start_fen, moves = svc.replay_moves(game)
    base = svc.to_game_out(db, [game])[0].model_dump()
    job = svc.latest_jobs(db, [game.id]).get(game.id)
    return GameDetail(
        **base,
        pgn=game.pgn,
        start_fen=start_fen,
        moves=[MoveOut(**m) for m in moves],
        clocks=game_clocks(game.pgn, game.time_control),
        latest_job=JobOut.model_validate(job) if job else None,
        note=game.note,
        move_notes=meta.move_notes_for(db, game.id),
    )


@router.patch("/{game_id}", response_model=GameDetail)
def update_game(
    game_id: uuid.UUID,
    body: GameUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Favourite, note and tags. Only what is sent changes; tags replace the whole set."""
    game = _owned(db, user, game_id)
    fields = body.model_dump(exclude_unset=True)
    try:
        if fields.get("favorite") is not None:
            game.favorite = fields["favorite"]
        if "note" in fields:
            meta.set_note(game, fields["note"])
        if fields.get("tags") is not None:
            meta.set_tags(db, game, fields["tags"])
    except meta.MetaError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _detail(db, game)


@router.put("/{game_id}/notes/{ply}", response_model=GameDetail)
def put_move_note(
    game_id: uuid.UUID,
    ply: int,
    body: MoveNoteUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Set (or, with empty text, remove) the note on one move."""
    game = _owned(db, user, game_id)
    try:
        meta.set_move_note(db, game, ply, body.text)
    except meta.MetaError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _detail(db, game)


@router.delete("/{game_id}", status_code=204)
def delete_game(
    game_id: uuid.UUID, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    svc.delete_game(db, _owned(db, user, game_id))
    return Response(status_code=204)
