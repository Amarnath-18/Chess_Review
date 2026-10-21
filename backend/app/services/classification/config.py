from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class ClassificationConfig:
    """All thresholds are win-probability points (0-100) unless noted."""

    # Loss bands (win-probability points lost vs. the engine's top move). They mirror the
    # expected-points bands Chess.com publishes: best 0, excellent <2, good 2-5, inaccuracy
    # 5-10, mistake 10-20, blunder 20+.
    best_loss: float = 0.5
    excellent_loss: float = 2.0
    inaccuracy_loss: float = 5.0
    mistake_loss: float = 10.0
    blunder_loss: float = 20.0

    # Great: top move that is also an "only move".
    great_gap: float = 15.0  # top line must beat the 2nd line by at least this much
    great_window_low: float = 10.0  # position must not already be decided...
    great_window_high: float = 90.0  # ...unless it is a long forced mate

    # Brilliant (after Chess.com's published description): a best or nearly-best move that is a
    # genuine piece sacrifice, that does not leave you in a bad position, and that was not
    # needed to stay completely winning (i.e. the best alternative is not already winning).
    brilliant_max_loss: float = 2.0  # "best or nearly best"
    sac_min_material: int = 2  # pawns' worth of material genuinely given up
    sac_horizon: int = 2  # PV plies after the opponent's reply in which it must stay unrecovered
    brilliant_max_without: float = 80.0  # win% of the best alternative must be below this
    brilliant_min_after: float = 45.0  # not worse than slightly worse afterwards
    # A "sacrifice" after which the opponent is simply mated next move is not a real sacrifice
    # (e.g. the sacrificed piece never had to be taken). Longer forced mates are fine: the
    # smothered mate Qg8+!! Rxg8 Nf7# is mate in 2 after the sacrifice and is the classic example.
    brilliant_trivial_mate: int = 1
    trivial_mate_max: int = 2  # ignore "sacrifices" that are just mate in <= this

    # Missed win.
    missed_win_before: float = 85.0
    missed_win_after: float = 60.0

    # Summary.
    swing_threshold: float = 20.0
    key_positions_top_k: int = 5

    @classmethod
    def from_dict(cls, data: dict) -> ClassificationConfig:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown classification settings: {sorted(unknown)}")
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    def config_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]
