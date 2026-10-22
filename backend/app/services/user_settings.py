"""Per-user preferences, always clamped to what the server allows."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User
from app.services import identity

KEYS = ("default_depth", "default_multipv", "import_count")


class SettingsError(ValueError):
    pass


def effective(user: User) -> dict[str, Any]:
    """The user's choices over the server defaults, never above the server's caps."""
    s = get_settings()
    stored: dict[str, Any] = user.settings or {}
    depth = int(stored.get("default_depth") or s.default_depth)
    lines = int(stored.get("default_multipv") or s.default_multipv)
    count = int(stored.get("import_count") or s.default_import_count)
    return {
        "default_depth": max(1, min(depth, s.max_depth)),
        "default_multipv": max(1, min(lines, s.max_multipv)),
        "import_count": count if count in (10, 20, 50) else s.default_import_count,
        "auto_analyze": stored.get("auto_analyze") is True,  # off unless the person turned it on
        "my_names": [n for n in stored.get("my_names", []) if isinstance(n, str)],
        "ai_explanations": stored.get("ai_explanations") is True,  # off unless the person opted in
        "explain_level": stored.get("explain_level") if stored.get("explain_level") in ("beginner", "intermediate", "advanced") else "intermediate",
    }


def update(db: Session, user: User, patch: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    new = dict(user.settings or {})
    for key, value in patch.items():
        if value is None:
            continue
        if key == "default_depth" and not 1 <= value <= s.max_depth:
            raise SettingsError(f"Depth must be between 1 and {s.max_depth}.")
        if key == "default_multipv" and not 1 <= value <= s.max_multipv:
            raise SettingsError(f"Engine lines must be between 1 and {s.max_multipv}.")
        if key == "my_names":
            try:
                value = identity.clean_names(value)
            except ValueError as exc:
                raise SettingsError(str(exc)) from exc
        new[key] = value
    if "my_names" in patch and patch["my_names"] is not None:
        identity.invalidate_scans(db, user.id)
    user.settings = new  # assign a new dict so the JSONB change is detected
    db.commit()
    return effective(user)
