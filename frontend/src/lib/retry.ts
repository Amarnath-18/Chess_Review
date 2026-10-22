import { Chess } from "chess.js";
import type { PositionAnalysis } from "../api/types";

/** A move this close to the engine's best (in winning chances) counts as found. */
export const CLOSE_ENOUGH = 2;

export interface RetryResult {
  uci: string;
  san: string;
  fenAfter: string;
  /** "best": the engine's first choice. "close": within CLOSE_ENOUGH of it. "worse": among the stored
   * lines but clearly worse. "unlisted": not among the stored lines, so it cannot be judged. */
  kind: "best" | "close" | "worse" | "unlisted";
  found: boolean;
  loss: number | null; // winning-chances points behind the best line (listed moves only)
  linesChecked: number;
}

/** Win% for the side to move, from White's perspective values. */
const forMover = (white: boolean, winPct: number) => (white ? winPct : 100 - winPct);

/**
 * Judge a try against the engine lines already saved for the position BEFORE the move, with no
 * new engine call. Honest limit: a good move outside the saved top lines is reported as
 * "unlisted", not as wrong.
 */
export function judgeRetry(before: PositionAnalysis, from: string, to: string): RetryResult | null {
  let chess: Chess;
  let move;
  try {
    chess = new Chess(before.fen);
    move = chess.move({ from, to, promotion: "q" });
  } catch {
    return null; // illegal
  }
  const uci = move.from + move.to + (move.promotion ?? "");
  const white = before.fen.split(" ")[1] === "w";
  const lines = before.lines;
  const base = { uci, san: move.san, fenAfter: chess.fen(), linesChecked: lines.length };
  const best = lines[0]?.eval.win_pct;
  const hit = lines.find((l) => l.move_uci === uci);
  if (!hit || best == null || hit.eval.win_pct == null) {
    return { ...base, kind: "unlisted", found: false, loss: null };
  }
  const loss = Math.max(0, forMover(white, best) - forMover(white, hit.eval.win_pct));
  if (hit.rank === 1) return { ...base, kind: "best", found: true, loss: 0 };
  if (loss <= CLOSE_ENOUGH) return { ...base, kind: "close", found: true, loss };
  return { ...base, kind: "worse", found: false, loss };
}

export function retryMessage(r: RetryResult): string {
  switch (r.kind) {
    case "best":
      return `${r.san} is the engine's first choice. Well found.`;
    case "close":
      return `${r.san} is a good alternative: only ${(r.loss ?? 0).toFixed(1)} points of winning chances behind the engine's first choice.`;
    case "worse":
      return `${r.san} is among the engine's top lines but gives up ${(r.loss ?? 0).toFixed(1)} points of winning chances compared with the best move.`;
    default:
      return `${r.san} is not among the engine's top ${r.linesChecked} move${r.linesChecked === 1 ? "" : "s"}, so it could not be judged. It may still be reasonable: only the saved lines are checked.`;
  }
}
