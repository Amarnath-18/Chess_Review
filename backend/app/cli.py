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


def cmd_bench(args: argparse.Namespace) -> int:
    """Time full-game analyses for a grid of depths and engine-line counts (markdown table)."""
    import os
    import time

    from app.services.analysis.runner import evaluate_game

    s = get_settings()
    depths = [int(x) for x in args.depths.split(",")]
    lines = [int(x) for x in args.lines.split(",")]
    print(f"cpus={os.cpu_count()} threads={s.engine_threads} hash={s.engine_hash_mb}MB "
          f"per-position cap={s.max_seconds_per_position:.0f}s\n")
    print("| game | plies | depth | lines | seconds | s/position |")
    print("|---|---|---|---|---|---|")
    with StockfishEngine() as engine:
        print(f"<!-- {engine.name} -->", file=sys.stderr)
        for path in args.pgn:
            with open(path, encoding="utf-8") as fh:
                game = chess.pgn.read_game(fh)
            if game is None:
                continue
            plies = len(list(game.mainline_moves()))
            for depth in depths:
                for n in lines:
                    start = time.perf_counter()
                    evaluate_game(game, engine, SearchLimit(depth=depth), multipv=n)
                    took = time.perf_counter() - start
                    print(f"| {os.path.basename(path)} | {plies} | {depth} | {n} | {took:.1f} | "
                          f"{took / (plies + 1):.2f} |", flush=True)
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
    b = sub.add_parser("bench", help="time analysis of games at several depths / line counts")
    b.add_argument("pgn", nargs="+")
    b.add_argument("--depths", default="12,16,20")
    b.add_argument("--lines", default="1,3")
    b.set_defaults(func=cmd_bench)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
