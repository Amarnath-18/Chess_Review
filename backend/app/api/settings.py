from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user
from app.config import get_settings
from app.models.user import User
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services import user_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _out(user: User) -> SettingsOut:
    s = get_settings()
    return SettingsOut(
        **user_settings.effective(user),
        max_depth=s.max_depth,
        max_multipv=s.max_multipv,
        retention_days=s.retention_days,
    )


@router.get("", response_model=SettingsOut)
def get_my_settings(user: User = Depends(require_user)):
    return _out(user)


@router.put("", response_model=SettingsOut)
def update_my_settings(
    body: SettingsUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    try:
        user_settings.update(db, user, body.model_dump(exclude_unset=True))
    except user_settings.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _out(user)
