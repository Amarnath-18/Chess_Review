import type { ClockInfo, MoveClass } from "../api/types";

export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "–";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/** Whether the side that played `ply` is White (the first move belongs to the side to move in `startFen`). */
export function moverIsWhite(ply: number, startFen: string): boolean {
  const whiteFirst = (startFen.split(" ")[1] ?? "w") === "w";
  return (ply % 2 === 1) === whiteFirst;
}

export interface ClockPoint {
  ply: number;
  x: number;
  y: number;
}

/** One side's remaining time over the game, as SVG points. Moves without a clock leave gaps. */
export function clockSeries(
  clocks: ClockInfo[],
  startFen: string,
  white: boolean,
  width: number,
  height: number,
  maxSeconds: number,
): ClockPoint[][] {
  const last = Math.max(1, clocks.length);
  const runs: ClockPoint[][] = [];
  let cur: ClockPoint[] = [];
  for (const c of clocks) {
    if (moverIsWhite(c.ply, startFen) !== white) continue;
    if (c.clock === null) {
      if (cur.length) runs.push(cur);
      cur = [];
      continue;
    }
    cur.push({
      ply: c.ply,
      x: (c.ply / last) * width,
      y: height - (Math.min(c.clock, maxSeconds) / Math.max(1, maxSeconds)) * height,
    });
  }
  if (cur.length) runs.push(cur);
  return runs;
}

export interface SideTime {
  moves: number;
  totalSpent: number; // seconds, over moves whose time is known
  timedMoves: number;
  troubleMoves: number;
  errors: number; // mistakes and blunders
  errorsInTrouble: number; // ...made while in time trouble
}

export function sideTimes(
  clocks: ClockInfo[],
  classes: (MoveClass | null)[] | undefined,
  startFen: string,
  white: boolean,
): SideTime {
  const out: SideTime = { moves: 0, totalSpent: 0, timedMoves: 0, troubleMoves: 0, errors: 0, errorsInTrouble: 0 };
  for (const c of clocks) {
    if (moverIsWhite(c.ply, startFen) !== white) continue;
    out.moves += 1;
    if (c.spent !== null) {
      out.totalSpent += c.spent;
      out.timedMoves += 1;
    }
    if (c.time_trouble) out.troubleMoves += 1;
    const cls = classes?.[c.ply];
    if (cls === "mistake" || cls === "blunder") {
      out.errors += 1;
      if (c.time_trouble) out.errorsInTrouble += 1;
    }
  }
  return out;
}

/** The slowest move by one side (ply and seconds), or null when no move has a known time. */
export function longestThink(clocks: ClockInfo[], startFen: string, white: boolean) {
  let best: { ply: number; spent: number } | null = null;
  for (const c of clocks) {
    if (moverIsWhite(c.ply, startFen) !== white || c.spent === null) continue;
    if (!best || c.spent > best.spent) best = { ply: c.ply, spent: c.spent };
  }
  return best;
}
