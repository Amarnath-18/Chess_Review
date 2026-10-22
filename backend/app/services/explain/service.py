"""Explaining one move of a person's review, with consent, limits and caching."""
from __future__ import annotations

import uuid
from urllib.parse import urlparse
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import AnalysisPosition, AnalysisRun
from app.models.explanation import LlmUsage, MoveExplanation
from app.models.game import Game
from app.models.user import User
from app.services.analysis.store import row_to_position
from app.services.explain.client import (
    ChatClient,
    LlmUnavailable,
    OpenAICompatibleClient,
    configured,
)
from app.services.explain.facts import build_facts
from app.services.explain.pipeline import explain
from app.services.explain.prompt import LEVELS
from app.services.ratelimit import SlidingWindow

DEFAULT_LEVEL = "intermediate"
_requests = SlidingWindow()  # server-wide, so a few friends cannot exhaust a free quota together


class ExplainError(Exception):
    def __init__(self, status_code: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


def provider_info() -> dict:
    """Who receives the data, for the privacy notice: the configured label, else the endpoint's name."""
    s = get_settings()
    label = s.llm_provider_label.strip()
    if not label:
        host = urlparse(s.llm_base_url).hostname or "the model provider"
        label = "OpenRouter" if host.endswith("openrouter.ai") else host
    return {"label": label}


def level_for(user: User) -> str:
    level = (user.settings or {}).get("explain_level")
    return level if level in LEVELS else DEFAULT_LEVEL


def enabled_for(user: User) -> bool:
    return (user.settings or {}).get("ai_explanations") is True


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def used_today(db: Session, user: User) -> int:
    """Requests today for this person: per invite code when there is one, else per browser.
    Outages (nothing was produced) do not count against the limit."""
    scope = (
        LlmUsage.invite_id == user.invite_id if user.invite_id else LlmUsage.user_id == user.id
    )
    return (
        db.scalar(
            select(func.count())
            .select_from(LlmUsage)
            .where(scope, LlmUsage.at >= _today_start(), LlmUsage.outcome != "failed")
        )
        or 0
    )


def remaining_today(db: Session, user: User) -> int:
    return max(0, get_settings().explain_daily_limit_per_user - used_today(db, user))


def stored(db: Session, run_id: uuid.UUID, level: str) -> list[MoveExplanation]:
    return list(
        db.scalars(
            select(MoveExplanation)
            .where(MoveExplanation.run_id == run_id, MoveExplanation.level == level)
            .order_by(MoveExplanation.ply)
        )
    )


def explain_ply(
    db: Session,
    user: User,
    game: Game,
    ply: int,
    client: ChatClient | None = None,
) -> tuple[MoveExplanation, bool]:
    """(explanation, was_cached). Raises ExplainError with a message fit to show the person."""
    s = get_settings()
    if not configured(s):
        raise ExplainError(503, "AI explanations are not set up on this server.")
    if not enabled_for(user):
        raise ExplainError(403, "Turn on AI explanations in Settings first.")
    run = db.get(AnalysisRun, game.current_analysis_id) if game.current_analysis_id else None
    if run is None or run.status != "completed":
        raise ExplainError(409, "Analyze this game first.")
    level = level_for(user)

    existing = db.scalar(
        select(MoveExplanation).where(
            MoveExplanation.run_id == run.id,
            MoveExplanation.ply == ply,
            MoveExplanation.level == level,
        )
    )
    if existing is not None:
        return existing, True

    rows = {
        r.ply: r
        for r in db.scalars(
            select(AnalysisPosition).where(
                AnalysisPosition.run_id == run.id, AnalysisPosition.ply.in_((ply - 1, ply))
            )
        )
    }
    before_row, after_row = rows.get(ply - 1), rows.get(ply)
    if ply < 1 or before_row is None or after_row is None or not after_row.played_move_uci:
        raise ExplainError(422, "That move has not been analyzed.")

    if used_today(db, user) >= s.explain_daily_limit_per_user:
        raise ExplainError(
            429, f"You have used today's {s.explain_daily_limit_per_user} explanations. Try again tomorrow."
        )
    if not _requests.allow("llm", s.llm_requests_per_minute, 60.0):
        raise ExplainError(
            429,
            "Many explanations were requested just now. Please try again in a minute.",
            _requests.retry_after("llm", 60.0),
        )

    facts = build_facts(
        row_to_position(before_row),
        row_to_position(after_row),
        after_row.played_move_uci,
        after_row.classification,
        ply,
    )
    if facts is None:
        raise ExplainError(422, "There is not enough engine data to explain this move.")

    client = client or OpenAICompatibleClient(s)
    try:
        result = explain(client, facts, level)
    except LlmUnavailable as exc:
        db.add(LlmUsage(user_id=user.id, invite_id=user.invite_id, model=client.model, outcome="failed"))
        db.commit()
        raise ExplainError(exc.status_code, exc.message, exc.retry_after) from exc

    row = MoveExplanation(
        run_id=run.id,
        ply=ply,
        level=level,
        model=client.model,
        text=result.text,
        source=result.source,
        motif=result.motif,
        facts=facts.data,
    )
    db.add(row)
    db.add(
        LlmUsage(
            user_id=user.id,
            invite_id=user.invite_id,
            model=client.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            seconds=result.seconds,
            outcome=result.outcome,
        )
    )
    db.commit()
    return row, False
