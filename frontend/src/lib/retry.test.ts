import { describe, expect, it } from "vitest";
import type { EngineLine, PositionAnalysis } from "../api/types";
import { CLOSE_ENOUGH, judgeRetry, retryMessage } from "./retry";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const BLACK_TO_MOVE = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";

const line = (rank: number, uci: string, san: string, win: number): EngineLine => ({
  rank,
  move_uci: uci,
  move_san: san,
  eval: { cp: 0, mate: null, terminal_result: null, display: "0.00", win_pct: win },
  pv_san: [san],
});

const position = (fen: string, lines: EngineLine[]): PositionAnalysis =>
  ({
    ply: 0, fen, eval: lines[0].eval, depth: 16, best_move_uci: lines[0].move_uci, best_move_san: lines[0].move_san,
    pv_san: [], lines, alt: null, played_move_uci: null, played_move_san: null, classification: null,
    loss_pct: null, missed_win: false, is_sacrifice: false,
  }) as PositionAnalysis;

const WHITE = position(START, [
  line(1, "e2e4", "e4", 54),
  line(2, "d2d4", "d4", 53), // 1 point behind
  line(3, "g1f3", "Nf3", 45), // 9 points behind
]);

describe("judging a retry against the saved engine lines", () => {
  it("accepts the engine's first choice", () => {
    const r = judgeRetry(WHITE, "e2", "e4")!;
    expect(r).toMatchObject({ kind: "best", found: true, san: "e4", uci: "e2e4", loss: 0 });
    expect(r.fenAfter.split(" ")[1]).toBe("b");
  });

  it("accepts a close alternative", () => {
    const r = judgeRetry(WHITE, "d2", "d4")!;
    expect(r.kind).toBe("close");
    expect(r.found).toBe(true);
    expect(r.loss).toBeCloseTo(1, 5);
    expect(r.loss!).toBeLessThanOrEqual(CLOSE_ENOUGH);
  });

  it("does not accept a listed move that is clearly worse", () => {
    const r = judgeRetry(WHITE, "g1", "f3")!;
    expect(r).toMatchObject({ kind: "worse", found: false });
    expect(r.loss).toBeCloseTo(9, 5);
    expect(retryMessage(r)).toContain("gives up 9.0 points");
  });

  it("says so, instead of calling it wrong, when the move is not among the saved lines", () => {
    const r = judgeRetry(WHITE, "a2", "a3")!;
    expect(r).toMatchObject({ kind: "unlisted", found: false, loss: null, linesChecked: 3 });
    expect(retryMessage(r)).toContain("not among the engine's top 3 moves");
    expect(retryMessage(r)).toContain("may still be reasonable");
  });

  it("measures loss from the point of view of the side to move", () => {
    // Black to move; win_pct is always White's, so a lower number is better for Black.
    const black = position(BLACK_TO_MOVE, [line(1, "e7e5", "e5", 46), line(2, "c7c5", "c5", 47.5)]);
    const r = judgeRetry(black, "c7", "c5")!;
    expect(r.kind).toBe("close");
    expect(r.loss).toBeCloseTo(1.5, 5);
  });

  it("returns null for an illegal move", () => {
    expect(judgeRetry(WHITE, "e2", "e5")).toBeNull();
  });
});
