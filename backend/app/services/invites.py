"""Invite codes: a small private-server gate (not an account system)."""
from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.invite import InviteCode
from app.models.user import User


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def create(db: Session, label: str) -> tuple[InviteCode, str]:
    """A new invite and its code. The code is returned once; only its hash is kept."""
    code = secrets.token_urlsafe(18)
    invite = InviteCode(label=label.strip()[:60] or "friend", code_hash=hash_code(code))
    db.add(invite)
    db.commit()
    return invite, code


def revoke(db: Session, invite_id: uuid.UUID) -> bool:
    invite = db.get(InviteCode, invite_id)
    if invite is None:
        return False
    if invite.revoked_at is None:
        invite.revoked_at = utcnow()
        db.commit()
    return True


def redeem(db: Session, user: User, code: str) -> InviteCode | None:
    """Bind this anonymous user to the invite the code belongs to. None if the code is wrong or revoked."""
    invite = db.scalar(select(InviteCode).where(InviteCode.code_hash == hash_code(code)))
    if invite is None or invite.revoked_at is not None:
        return None
    user.invite_id = invite.id
    invite.last_used_at = utcnow()
    db.commit()
    return invite


def invite_for(db: Session, user: User) -> InviteCode | None:
    return db.get(InviteCode, user.invite_id) if user.invite_id else None


def is_active(invite: InviteCode | None) -> bool:
    return invite is not None and invite.revoked_at is None
