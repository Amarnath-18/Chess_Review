"""Personal statistics over the person's own analyzed games.

Honesty rules: every figure carries its sample size; anything under the minimum sample is marked
`reliable: false` and is never turned into a "weak spot" claim; games where the person cannot be
identified are left out and counted, never guessed.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisPosition
from app.models.game import Game
from app.models.user import User
from app.services import identity
from app.services.analysis.store import _score_from
from app.services.classification.accuracy import game_accuracy
from app.services.classification.score import win_pct_white
from app.services.clocks import parse_time_control
from app.services.openings import book_run

MIN_GAMES = 10
MIN_MOVES = 30
MAX_GAMES = 200
OPENING_PLIES = 20  # the first ten moves of each side
ENDGAME_MATERIAL = 26  # both sides' pieces (not pawns) add up to at most this
_PIECE = {"q": 9, "r": 5, "b": 3, "n": 3}
WEAK_SPOT_FACTOR = 1.5


def phase_of(ply: int, fen_before: str) -> str:
    """"opening" for the first ten moves, then "endgame" once little material is left."""
    if ply <= OPENING_PLIES:
        return "opening"
    placement = fen_before.split()[0].lower()
    material = sum(_PIECE.get(c, 0) for c in placement)
    return "endgame" if material <= ENDGAME_MATERIAL else "middlegame"


def time_class(time_control: str | None) -> str:
    """bullet / blitz / rapid / classical by the usual estimate base + 40 x increment."""
    tc = parse_time_control(time_control)
    if tc is None:
        return "unknown"
    total = tc[0] + 40 * tc[1]
    if total < 180:
        return "bullet"
    if total < 480:
        return "blitz"
    if total < 1500:
        return "rapid"
    return "classical"


@dataclass
class Bucket:
    games: set = field(default_factory=set)
    moves: int = 0
    inaccuracies: int = 0
    mistakes: int = 0
    blunders: int = 0

    def add(self, game_id, cls: str | None) -> None:
        self.games.add(game_id)
        self.moves += 1
        if cls == "inaccuracy":
            self.inaccuracies += 1
        elif cls == "mistake":
            self.mistakes += 1
        elif cls == "blunder":
            self.blunders += 1

    def out(self, key: str, label: str) -> dict:
        serious = self.mistakes + self.blunders
        return {
            "key": key,
            "label": label,
            "games": len(self.games),
            "moves": self.moves,
            "inaccuracies": self.inaccuracies,
            "mistakes": self.mistakes,
            "blunders": self.blunders,
            "serious_per_100": round(100 * serious / self.moves, 1) if self.moves else None,
            "reliable": self.moves >= MIN_MOVES,
        }


def _my_side_result(result: str, color: str) -> str | None:
    if result == "1/2-1/2":
        return "draw"
    if result == "1-0":
        return "win" if color == "white" else "loss"
    if result == "0-1":
        return "win" if color == "black" else "loss"
    return None  # unfinished or unknown


def _highlights(dimension: str, buckets: list[dict], overall: float | None) -> list[str]:
    """One careful sentence when a reliable bucket is clearly worse than the rest."""
    reliable = [b for b in buckets if b["reliable"] and b["serious_per_100"] is not None]
    if overall is None or len(reliable) < 2:
        return []
    worst = max(reliable, key=lambda b: b["serious_per_100"])
    if worst["serious_per_100"] >= WEAK_SPOT_FACTOR * overall and worst["serious_per_100"] > 0:
        return [
            f"{dimension}: {worst['label']} stands out, with {worst['serious_per_100']} mistakes or "
            f"blunders per 100 moves against {overall} overall ({worst['moves']} moves)."
        ]
    return []


def compute(db: Session, user: User) -> dict:
    names = identity.my_names(db, user)
    games = list(
        db.scalars(
            select(Game)
            .where(Game.owner_id == user.id, Game.current_analysis_id.is_not(None))
            .order_by(Game.played_at.desc().nulls_last(), Game.created_at.desc())
            .limit(MAX_GAMES)
        )
    )
    included: list[tuple[Game, str]] = []
    unidentified = 0
    for g in games:
        color = identity.my_color(g, names) if names else None
        if color is None:
            unidentified += 1
        else:
            included.append((g, color))

    rows_by_run: dict[uuid.UUID, list[AnalysisPosition]] = defaultdict(list)
    run_ids = [g.current_analysis_id for g, _ in included]
    if run_ids:
        for row in db.scalars(
            select(AnalysisPosition)
            .where(AnalysisPosition.run_id.in_(run_ids))
            .order_by(AnalysisPosition.run_id, AnalysisPosition.ply)
        ):
            rows_by_run[row.run_id].append(row)

    phases: dict[str, Bucket] = defaultdict(Bucket)
    colors: dict[str, Bucket] = defaultdict(Bucket)
    clocks: dict[str, Bucket] = defaultdict(Bucket)
    overall = Bucket()
    trend: list[dict] = []
    families: dict[str, dict] = {}

    for game, color in included:
        rows = rows_by_run.get(game.current_analysis_id, [])
        if len(rows) < 2:
            continue
        mine_white = color == "white"
        wins: list[float | None] = []
        for r in rows:
            s = _score_from(r.score_cp, r.score_mate, r.terminal_result)
            wins.append(win_pct_white(s) if s is not None else None)
        movers = [rows[i].fen.split()[1] == "w" for i in range(len(rows) - 1)]
        acc = game_accuracy(wins, [r.loss_pct for r in rows[1:]], movers)[color]
        tclass = time_class(game.time_control)

        for k in range(1, len(rows)):
            if movers[k - 1] != mine_white:
                continue
            cls = rows[k].classification
            if cls is None:
                continue  # an unevaluated move is not counted as good
            overall.add(game.id, cls)
            colors[color].add(game.id, cls)
            clocks[tclass].add(game.id, cls)
            phases[phase_of(k, rows[k - 1].fen)].add(game.id, cls)

        trend.append(
            {
                "game_id": str(game.id),
                "played_at": game.played_at.isoformat() if game.played_at else None,
                "accuracy": acc,
                "color": color,
                "opponent": game.black if mine_white else game.white,
            }
        )

        hits = [h for h in book_run(rows[0].fen, [r.fen for r in rows[1:]]) if h]
        family = hits[-1][1].split(":")[0] if hits else "Unknown opening"
        fam = families.setdefault(
            family, {"games": 0, "win": 0, "draw": 0, "loss": 0, "acc": []}
        )
        fam["games"] += 1
        outcome = _my_side_result(game.result, color)
        if outcome:
            fam[outcome] += 1
        if acc is not None:
            fam["acc"].append(acc)

    trend.sort(key=lambda t: t["played_at"] or "")
    overall_rate = overall.out("all", "All moves")["serious_per_100"]

    def listing(src: dict[str, Bucket], order: list[str], labels: dict[str, str]) -> list[dict]:
        return [src[k].out(k, labels[k]) for k in order if k in src]

    by_phase = listing(
        phases,
        ["opening", "middlegame", "endgame"],
        {"opening": "Opening (first 10 moves)", "middlegame": "Middlegame", "endgame": "Endgame"},
    )
    by_color = listing(colors, ["white", "black"], {"white": "As White", "black": "As Black"})
    by_time = listing(
        clocks,
        ["bullet", "blitz", "rapid", "classical", "unknown"],
        {
            "bullet": "Bullet",
            "blitz": "Blitz",
            "rapid": "Rapid",
            "classical": "Classical",
            "unknown": "Unknown time control",
        },
    )
    openings = sorted(
        (
            {
                "name": name,
                "games": f["games"],
                "wins": f["win"],
                "draws": f["draw"],
                "losses": f["loss"],
                "accuracy": round(sum(f["acc"]) / len(f["acc"]), 1) if f["acc"] else None,
                "reliable": f["games"] >= MIN_GAMES,
            }
            for name, f in families.items()
        ),
        key=lambda o: (-o["games"], o["name"]),
    )

    highlights: list[str] = []
    for dim, buckets in (("Phase", by_phase), ("Colour", by_color), ("Time control", by_time)):
        highlights += _highlights(dim, buckets, overall_rate)

    return {
        "needs_names": not names,
        "games_analyzed": len(games),
        "games_included": len(trend),
        "games_unidentified": unidentified,  # analyzed, but neither side matched "my names"
        "min_games": MIN_GAMES,
        "min_moves": MIN_MOVES,
        "overall": overall.out("all", "All moves"),
        "by_phase": by_phase,
        "by_color": by_color,
        "by_time_control": by_time,
        "openings": openings,
        "trend": trend,
        "highlights": highlights,
    }
