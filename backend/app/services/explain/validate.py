"""Checking what the model said against the facts, and the facts-only fallback.

This is the grounding: the model may phrase things, but it may not introduce a move, an
evaluation or a mate that the engine data does not contain. Anything that fails is rejected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.services.explain.facts import MOTIFS, Facts, norm_san

MAX_LENGTH = 900

# A move written in SAN: castling, piece moves, pawn captures, pawn pushes / bare squares.
_SAN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)"
    r"[+#]?(?![A-Za-z0-9])"
)
_BARE_SQUARE = re.compile(r"^[a-h][1-8]$")
_MATE = re.compile(r"\bmate[sd]? in (\d+)", re.I)
_SIGNED = re.compile(r"(?<![\w.])[+-]\d+(?:\.\d+)?(?![\d])")
_EVAL_TOLERANCE = 0.15


@dataclass
class Checked:
    ok: bool
    explanation: str = ""
    mentioned_moves: list[str] | None = None
    motif: str | None = None
    problems: list[str] | None = None


def parse_reply(text: str) -> dict | None:
    """The JSON object in the model's reply (some models wrap it in code fences or add prose)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def check(text: str, facts: Facts) -> Checked:
    """Accept the reply only if every claim in it is supported by `facts`."""
    problems: list[str] = []
    data = parse_reply(text)
    if data is None:
        return Checked(False, problems=["The reply was not a JSON object."])
    explanation = data.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return Checked(False, problems=['The "explanation" field is missing or empty.'])
    explanation = " ".join(explanation.split())
    if len(explanation) > MAX_LENGTH:
        problems.append(f"The explanation is longer than {MAX_LENGTH} characters.")
    if re.search(r"https?://|www\.", explanation, re.I):
        problems.append("The explanation must not contain links.")

    allowed = {norm_san(m) for m in facts.allowed_moves}
    mentioned = data.get("mentioned_moves", [])
    if not isinstance(mentioned, list) or not all(isinstance(m, str) for m in mentioned):
        problems.append('"mentioned_moves" must be a list of moves.')
        mentioned = []
    for move in mentioned:
        if norm_san(move) not in allowed:
            problems.append(f'"{move}" is not one of the allowed moves.')

    for match in _SAN.finditer(explanation):
        token = norm_san(match.group(0))
        if token in allowed:
            continue
        if _BARE_SQUARE.match(token) and token in facts.allowed_squares:
            continue  # naming a square that is on the board in this position is fine
        problems.append(f'The explanation mentions "{match.group(0)}", which is not an allowed move.')

    for match in _MATE.finditer(explanation):
        if int(match.group(1)) not in facts.mates:
            problems.append(f'It claims "{match.group(0)}", which the engine data does not support.')
    for match in _SIGNED.finditer(explanation):
        value = abs(float(match.group(0)))
        if not any(abs(value - abs(e)) <= _EVAL_TOLERANCE for e in facts.evals):
            problems.append(f'It quotes an evaluation of "{match.group(0)}" that is not in the engine data.')

    motif = data.get("motif")
    if motif is not None:
        if not isinstance(motif, str) or motif not in MOTIFS:
            problems.append(f'"motif" must be null or one of: {", ".join(MOTIFS)}.')
            motif = None
        elif motif not in facts.data.get("motifs", []):
            problems.append(f'The motif "{motif}" is not among the facts.')
            motif = None

    # report each problem once, in order
    problems = list(dict.fromkeys(problems))
    if problems:
        return Checked(False, explanation, list(mentioned), motif, problems)
    return Checked(True, explanation, list(mentioned), motif, None)


def fallback_text(facts: Facts) -> str:
    """A plain explanation assembled from the facts alone, used when the model's reply cannot be trusted."""
    d = facts.data
    played, best = d["played"], d["engine_best"]
    parts = [f"You played {played['san']}."]
    if d["played_is_engine_best"]:
        parts.append("That is the engine's first choice.")
    else:
        lost = d["win_chance_lost_points"]
        label = (d.get("classification") or "").replace("_", " ")
        if lost >= 1:
            prefix = f"This was rated a {label}: it" if label else "It"
            parts.append(
                f"{prefix} cost {lost} points of winning chances "
                f"(from {d['win_chance_before_percent']}% to {d['win_chance_after_percent']}%)."
            )
        parts.append(f"The engine preferred {best['san']}.")
    after = d["after_the_played_move"]
    if after["you_get_mated_in"]:
        parts.append(f"After your move the opponent can force mate in {after['you_get_mated_in']}.")
    elif after["opponents_best_reply"]:
        parts.append(f"The opponent's best reply is {after['opponents_best_reply']['san']}.")
    missed = d["missed"]
    if missed["you_could_have_mated_in"] and not d["played_is_engine_best"]:
        parts.append(f"{best['san']} would have led to mate in {missed['you_could_have_mated_in']}.")
    elif missed["capture_available"] and not d["played_is_engine_best"]:
        parts.append(f"{best['san']} would have won a {missed['capture_available']}.")
    for piece in after["pieces_newly_attacked_and_losable"][:2]:
        parts.append(f"Your {piece['piece']} on {piece['square']} could be lost.")
    return " ".join(parts)
