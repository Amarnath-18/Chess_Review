import { Chess } from "chess.js";

/** A move from a drop or typed entry, as UCI plus the position it leads to. Null if illegal. */
export function judgeMove(fen: string, from: string, to: string): { uci: string; fenAfter: string } | null {
  try {
    const c = new Chess(fen);
    const m = c.move({ from, to, promotion: "q" });
    return { uci: m.from + m.to + (m.promotion ?? ""), fenAfter: c.fen() };
  } catch {
    return null;
  }
}
