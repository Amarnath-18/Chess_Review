"""Developer CLI: analyze a PGN file and print the review.

    docker compose run --rm worker python -m app.cli analyze tests/fixtures/short_game.pgn
"""
from __future__ import annotations

import argparse
import json
import sys

import chess
import chess.pgn

from app.config import get_settings
from app.services.analysis.engine import SearchLimit, StockfishEngine
from app.services.analysis.runner import analyze_game


def cmd_analyze(args: argparse.Namespace) -> int:
    with open(args.pgn, encoding="utf-8") as fh:
        game = chess.pgn.read_game(fh)
    if game is None:
        print("no game found in file", file=sys.stderr)
        return 1

    limit = SearchLimit(depth=args.depth, nodes=args.nodes)
    with StockfishEngine() as engine:
        analysis = analyze_game(
            game,
            engine,
            limit,
            multipv=args.multipv,
            on_progress=lambda d, t: print(f"\r{d}/{t}", end="", file=sys.stderr),
        )
    print(file=sys.stderr)

    print(f"{analysis.engine_name}  limit={analysis.limit.describe()}  multipv={analysis.multipv}")
    print(f"{'ply':>3}  {'move':<8} {'eval':>7}  {'best':<6} {'class':<11} {'loss':>5}  flags")
    for i, (san, res) in enumerate(zip(analysis.moves_san, analysis.results, strict=True)):
        after = analysis.positions[i + 1]
        before = analysis.positions[i]
        ev = after.score.display() if after.score else "n/a"
        best = (before.top.move if before.top else None) or "-"
        if res is None:
            cls, loss, flags = "n/a", "", ""
        else:
            cls, loss = res.classification.value, f"{res.loss:5.1f}"
            flag_map = {"missed_win": res.missed_win, "sac": res.is_sacrifice}
            flags = ",".join(name for name, on in flag_map.items() if on)
        mark = f"{i // 2 + 1}." if i % 2 == 0 else "   "
        print(f"{i + 1:>3}  {mark}{san:<6} {ev:>7}  {best:<6} {cls:<11} {loss:>5}  {flags}")
    print(json.dumps(analysis.summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze")
    p.add_argument("pgn")
    p.add_argument("--depth", type=int, default=get_settings().default_depth)
    p.add_argument("--nodes", type=int, default=None)
    p.add_argument("--multipv", type=int, default=2)
    p.set_defaults(func=cmd_analyze)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
