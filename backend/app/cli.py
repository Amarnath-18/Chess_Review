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


def cmd_llm_test(args: argparse.Namespace) -> int:
    """Bake-off for the explanation model: analyze real games with Stockfish, then ask the configured
    model (LLM_BASE_URL / LLM_MODEL / LLM_API_KEY) to explain the biggest mistakes, and report how
    often its replies were valid, needed a retry, or had to be replaced by the plain fallback.

        docker compose run --rm worker python -m app.cli llm-test tests/fixtures/opera_game.pgn
    """
    from app.services.explain.client import OpenAICompatibleClient, LlmUnavailable, configured
    from app.services.explain.facts import build_facts
    from app.services.explain.pipeline import explain

    settings = get_settings()
    if not configured(settings):
        print("Set LLM_MODEL and LLM_API_KEY in .env first (see README, AI explanations).", file=sys.stderr)
        return 1
    client = OpenAICompatibleClient(settings)
    candidates = []  # (loss, before, after, uci, class, ply)
    with StockfishEngine() as engine:
        for path in args.pgn:
            with open(path, encoding="utf-8") as fh:
                game = chess.pgn.read_game(fh)
            if game is None:
                continue
            a = analyze_game(game, engine, SearchLimit(depth=args.depth), multipv=3)
            for i, res in enumerate(a.results):
                if res is not None and res.loss >= 8:
                    candidates.append((res.loss, a.positions[i], a.positions[i + 1], a.moves_uci[i], res.classification.value, i + 1))
    candidates.sort(key=lambda c: -c[0])
    chosen = candidates[: args.positions]
    print(f"model={settings.llm_model}  base={settings.llm_base_url}  positions={len(chosen)}")

    outcomes: dict[str, int] = {}
    seconds = 0.0
    for loss, before, after, uci, cls, ply in chosen:
        facts = build_facts(before, after, uci, cls, ply)
        if facts is None:
            continue
        try:
            result = explain(client, facts, args.level)
        except LlmUnavailable as exc:
            print(f"ply {ply:>3}  UNAVAILABLE: {exc.message}")
            outcomes["unavailable"] = outcomes.get("unavailable", 0) + 1
            continue
        outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
        seconds += result.seconds
        print(f"ply {ply:>3}  {result.outcome:<8} {result.seconds:5.1f}s  {result.text}")
        for problem in result.problems:
            print(f"           rejected: {problem}")
    total = sum(outcomes.values()) or 1
    print()
    for name in ("valid", "retried", "fallback", "unavailable"):
        if outcomes.get(name):
            print(f"{name:<12} {outcomes[name]:>3}  ({100 * outcomes[name] / total:.0f}%)")
    print(f"average time {seconds / total:.1f}s per explanation")
    return 0


def cmd_llm_usage(args: argparse.Namespace) -> int:
    """How the explanation model has been doing: outcomes, speed and who used it today."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models.explanation import LlmUsage
    from app.models.invite import InviteCode

    with SessionLocal() as db:
        rows = db.execute(
            select(LlmUsage.outcome, func.count(), func.avg(LlmUsage.seconds), func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out))
            .group_by(LlmUsage.outcome)
        ).all()
        total = sum(r[1] for r in rows) or 1
        print("outcome      requests   share   avg seconds   tokens")
        for outcome, n, avg, tokens in sorted(rows):
            print(f"{outcome:<12} {n:>8}  {100 * n / total:>4.0f}%   {avg or 0:>10.1f}   {tokens or 0:>6}")
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today = db.execute(
            select(InviteCode.label, func.count())
            .select_from(LlmUsage)
            .outerjoin(InviteCode, InviteCode.id == LlmUsage.invite_id)
            .where(LlmUsage.at >= midnight, LlmUsage.outcome != "failed")
            .group_by(InviteCode.label)
        ).all()
        print("\ntoday:")
        for label, n in today:
            print(f"  {label or '(no invite)'}: {n}")
    return 0


def cmd_invite(args: argparse.Namespace) -> int:
    """Manage invite codes for a private server (ACCESS_REQUIRED=true)."""
    import uuid

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models.invite import InviteCode
    from app.models.user import User
    from app.services import invites

    with SessionLocal() as db:
        if args.action == "create":
            invite, code = invites.create(db, args.label)
            print(f"Invite for {invite.label!r} (id {invite.id}).")
            print(f"Code (shown once, only a hash is stored): {code}")
            return 0
        if args.action == "revoke":
            try:
                ok = invites.revoke(db, uuid.UUID(args.id))
            except ValueError:
                ok = False
            print("revoked" if ok else "no such invite", file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        rows = db.execute(
            select(InviteCode, func.count(User.id))
            .outerjoin(User, User.invite_id == InviteCode.id)
            .group_by(InviteCode.id)
            .order_by(InviteCode.created_at)
        ).all()
        print(f"{'id':<36}  {'label':<20} {'status':<8} {'browsers':>8}  last used")
        for inv, browsers in rows:
            status = "revoked" if inv.revoked_at else "active"
            used = inv.last_used_at.strftime("%Y-%m-%d %H:%M") if inv.last_used_at else "never"
            print(f"{inv.id}  {inv.label:<20} {status:<8} {browsers:>8}  {used}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("llm-test", help="try the configured explanation model on real mistakes")
    t.add_argument("pgn", nargs="+")
    t.add_argument("--depth", type=int, default=12)
    t.add_argument("--positions", type=int, default=8)
    t.add_argument("--level", default="intermediate", choices=["beginner", "intermediate", "advanced"])
    t.set_defaults(func=cmd_llm_test)
    u = sub.add_parser("llm-usage", help="how the explanation model has been used")
    u.set_defaults(func=cmd_llm_usage)
    inv = sub.add_parser("invite", help="create, list or revoke invite codes (private server)")
    inv_sub = inv.add_subparsers(dest="action", required=True)
    inv_sub.add_parser("list")
    c = inv_sub.add_parser("create")
    c.add_argument("label", help="who it is for, e.g. a first name")
    r = inv_sub.add_parser("revoke")
    r.add_argument("id")
    inv.set_defaults(func=cmd_invite)
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
