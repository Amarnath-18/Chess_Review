"""Facts in, checked explanation out: ask the model, validate, retry once, else fall back."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.explain.client import ChatClient, Completion
from app.services.explain.facts import Facts
from app.services.explain.prompt import build_messages
from app.services.explain.validate import check, fallback_text


@dataclass
class Explained:
    text: str
    source: str  # "ai": the model's words, validated. "fallback": built from the facts alone.
    outcome: str  # "valid" | "retried" | "fallback"
    motif: str | None
    mentioned_moves: list[str]
    problems: list[str]  # why a reply was rejected (empty when the first reply was fine)
    tokens_in: int
    tokens_out: int
    seconds: float


def explain(client: ChatClient, facts: Facts, level: str) -> Explained:
    """One or two model calls. `LlmUnavailable` from the client is not caught: an unreachable
    model is an outage, not a bad answer, and the caller reports it as such."""
    tokens_in = tokens_out = 0
    seconds = 0.0
    problems: list[str] = []
    for attempt in (1, 2):
        done: Completion = client.complete(build_messages(facts, level, problems or None))
        tokens_in += done.tokens_in
        tokens_out += done.tokens_out
        seconds += done.seconds
        checked = check(done.text, facts)
        if checked.ok:
            return Explained(
                text=checked.explanation,
                source="ai",
                outcome="valid" if attempt == 1 else "retried",
                motif=checked.motif,
                mentioned_moves=checked.mentioned_moves or [],
                problems=problems,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                seconds=seconds,
            )
        problems = checked.problems or ["The reply could not be checked."]
    return Explained(
        text=fallback_text(facts),
        source="fallback",
        outcome="fallback",
        motif=None,
        mentioned_moves=[],
        problems=problems,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        seconds=seconds,
    )
