import type { PositionAnalysis } from "../api/types";

export interface GraphPoint {
  ply: number;
  x: number;
  y: number | null; // null = evaluation unavailable (leaves a gap, never plotted as 0)
  mate: boolean;
}

/** Map positions to SVG coordinates. Higher on screen = better for White (win% 100 = top). */
export function buildGraphPoints(
  positions: PositionAnalysis[],
  width: number,
  height: number,
): GraphPoint[] {
  const last = Math.max(1, positions.length - 1);
  return positions.map((p) => {
    const w = p.eval.win_pct;
    return {
      ply: p.ply,
      x: (p.ply / last) * width,
      y: w === null || w === undefined ? null : height - (w / 100) * height,
      mate: p.eval.mate !== null || (p.eval.terminal_result !== null && p.eval.terminal_result !== "1/2-1/2"),
    };
  });
}

/** Split into runs of consecutive plotted points so missing data breaks the line. */
export function segments(points: GraphPoint[]): GraphPoint[][] {
  const out: GraphPoint[][] = [];
  let cur: GraphPoint[] = [];
  for (const p of points) {
    if (p.y === null) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push(p);
  }
  if (cur.length) out.push(cur);
  return out;
}

export const linePath = (seg: GraphPoint[]) =>
  seg.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${(p.y as number).toFixed(1)}`).join(" ");

export const areaPath = (seg: GraphPoint[], height: number) =>
  `${linePath(seg)} L${seg[seg.length - 1].x.toFixed(1)},${height} L${seg[0].x.toFixed(1)},${height} Z`;

/** Ply nearest to a horizontal position (0..width). */
export function plyAtX(x: number, width: number, totalPlies: number): number {
  if (width <= 0 || totalPlies <= 0) return 0;
  const ply = Math.round((x / width) * totalPlies);
  return Math.max(0, Math.min(totalPlies, ply));
}
