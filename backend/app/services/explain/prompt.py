"""The request sent to the language model. Only facts about positions and moves go in: never
player names, game headers, or the whole game."""
from __future__ import annotations

import json

from app.services.explain.facts import MOTIFS, Facts

LEVELS = ("beginner", "intermediate", "advanced")

LEVEL_HINT = {
    "beginner": "Use plain words, avoid jargon, and explain ideas such as 'hanging' or 'fork' briefly.",
    "intermediate": "Use normal chess vocabulary; keep it short.",
    "advanced": "Be concise and concrete; no basic explanations.",
}

SYSTEM = """You explain one chess move to a {level} player, using ONLY the engine facts you are given.
{hint}

Rules:
- Write 2 to 4 sentences. Speak to the player as "you".
- Mention a move only if it appears in "allowed_moves", written exactly as given (standard algebraic notation).
- Do not state evaluations, mates or captures that are not in the facts. Do not invent threats, plans or lines.
- If the facts do not explain why the move was bad, say what the engine preferred and how much it cost, and stop.
- Reply with one JSON object and nothing else:
  {{"explanation": "<text>", "mentioned_moves": ["<each move you wrote>"], "motif": null}}
  "motif" is null, or one of {motifs}, and only if it is listed in the facts' "motifs"."""


def build_messages(facts: Facts, level: str, problems: list[str] | None = None) -> list[dict]:
    level = level if level in LEVELS else "intermediate"
    system = SYSTEM.format(level=level, hint=LEVEL_HINT[level], motifs=json.dumps(list(MOTIFS)))
    user = "Engine facts:\n" + json.dumps(facts.data, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if problems:
        messages.append(
            {
                "role": "user",
                "content": "Your previous reply was rejected for these reasons:\n- "
                + "\n- ".join(problems)
                + "\nWrite a corrected reply that follows the rules.",
            }
        )
    return messages
