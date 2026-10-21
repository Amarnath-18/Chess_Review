from __future__ import annotations

import chess

from app.services.classification.classify import MoveClass, MoveResult, PositionEval
from app.services.classification.config import ClassificationConfig
from app.services.classification.score import win_pct_white


def summarize(
    positions: list[PositionEval],
    results: list[MoveResult | None],
    config: ClassificationConfig,
    complete: bool,
) -> dict:
    """Review summary built only from saved classifications.

    Moves without a classification are counted as `unanalyzed`, never as evaluated.
    """
    counts = {
        "white": {c.value: 0 for c in MoveClass},
        "black": {c.value: 0 for c in MoveClass},
    }
    missed_wins = {"white": 0, "black": 0}
    swings: list[dict] = []
    key: dict[int, list[str]] = {}
    unanalyzed = 0

    for i, result in enumerate(results):
        ply = i + 1
        before, after = positions[i], positions[i + 1]
        side = "white" if chess.Board(before.fen).turn == chess.WHITE else "black"
        if result is None:
            unanalyzed += 1
            continue
        counts[side][result.classification.value] += 1
        if result.missed_win:
            missed_wins[side] += 1
            key.setdefault(ply, []).append("missed_win")
        if before.score is not None and after.score is not None:
            delta = win_pct_white(after.score) - win_pct_white(before.score)
            if abs(delta) >= config.swing_threshold:
                swings.append({"ply": ply, "delta_white": round(delta, 1)})
                key.setdefault(ply, []).append("swing")

    # Only moves that cost at least an "inaccuracy" are worth flagging; tiny losses are noise.
    ranked = sorted(
        (
            (i + 1, r.loss)
            for i, r in enumerate(results)
            if r is not None and r.loss >= config.inaccuracy_loss
        ),
        key=lambda t: -t[1],
    )
    for ply, _ in ranked[: config.key_positions_top_k]:
        key.setdefault(ply, []).append("large_loss")

    return {
        "complete": complete and unanalyzed == 0,
        "total_moves": len(results),
        "analyzed_moves": len(results) - unanalyzed,
        "unanalyzed_moves": unanalyzed,
        "counts": counts,
        "missed_wins": missed_wins,
        "swings": swings,
        "key_positions": [{"ply": p, "reasons": r} for p, r in sorted(key.items())],
    }
