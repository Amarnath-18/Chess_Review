import { describe, expect, it } from "vitest";
import type { PositionAnalysis } from "../api/types";
import { durationText, runTookText } from "./format";
import { areaPath, buildGraphPoints, linePath, plyAtX, segments } from "./graph";
import { buildRows, clampPly, plyLabel } from "./moves";
import {
  currentFen,
  formatVariation,
  fromSans,
  playMove,
  startVariation,
  stepVariation,
} from "./variation";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const mv = (ply: number, san: string) => ({ ply, san });

describe("buildRows", () => {
  it("pairs White and Black moves", () => {
    const rows = buildRows([mv(1, "e4"), mv(2, "e5"), mv(3, "Nf3")], START);
    expect(rows).toEqual([
      { number: 1, white: mv(1, "e4"), black: mv(2, "e5") },
      { number: 2, white: mv(3, "Nf3") },
    ]);
  });

  it("handles a start position where Black moves first", () => {
    const fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 7";
    const rows = buildRows([mv(1, "Nf6"), mv(2, "Nc3")], fen);
    expect(rows[0]).toEqual({ number: 7, black: mv(1, "Nf6") });
    expect(rows[1]).toEqual({ number: 8, white: mv(2, "Nc3") });
  });

  it("labels plies with correct move numbers", () => {
    expect(plyLabel(0, "", START)).toBe("Start position");
    expect(plyLabel(1, "e4", START)).toBe("1. e4");
    expect(plyLabel(2, "e5", START)).toBe("1... e5");
    expect(plyLabel(3, "Nf3", START)).toBe("2. Nf3");
    const blackFirst = "8/8/8/8/8/8/8/k6K b - - 0 7";
    expect(plyLabel(1, "Kb2", blackFirst)).toBe("7... Kb2");
    expect(plyLabel(2, "Kg2", blackFirst)).toBe("8. Kg2");
  });

  it("clamps plies", () => {
    expect(clampPly(-3, 10)).toBe(0);
    expect(clampPly(99, 10)).toBe(10);
  });
});

const pos = (ply: number, win: number | null, extra: Partial<PositionAnalysis["eval"]> = {}) =>
  ({
    ply,
    eval: { cp: null, mate: null, terminal_result: null, display: null, win_pct: win, ...extra },
  }) as PositionAnalysis;

describe("graph", () => {
  it("puts better-for-White higher up and spans the full width", () => {
    const pts = buildGraphPoints([pos(0, 100), pos(1, 50), pos(2, 0)], 600, 100);
    expect(pts.map((p) => p.x)).toEqual([0, 300, 600]);
    expect(pts.map((p) => p.y)).toEqual([0, 50, 100]);
  });

  it("never plots a missing evaluation as a draw: it leaves a gap", () => {
    const pts = buildGraphPoints([pos(0, 60), pos(1, null), pos(2, 40)], 200, 100);
    expect(pts[1].y).toBeNull();
    const segs = segments(pts);
    expect(segs).toHaveLength(2);
    expect(segs.map((s) => s.length)).toEqual([1, 1]);
  });

  it("flags forced mates and checkmate, but not drawn or ordinary positions", () => {
    const pts = buildGraphPoints(
      [
        pos(0, 50),
        pos(1, 100, { mate: 3 }),
        pos(2, 0, { terminal_result: "0-1" }),
        pos(3, 50, { terminal_result: "1/2-1/2" }),
      ],
      300,
      100,
    );
    expect(pts.map((p) => p.mate)).toEqual([false, true, true, false]);
  });

  it("builds svg paths", () => {
    const seg = buildGraphPoints([pos(0, 50), pos(1, 50)], 100, 100);
    expect(linePath(seg)).toBe("M0.0,50.0 L100.0,50.0");
    expect(areaPath(seg, 100)).toContain("Z");
  });

  it("maps a click position to the nearest ply, clamped", () => {
    expect(plyAtX(0, 600, 10)).toBe(0);
    expect(plyAtX(299, 600, 10)).toBe(5);
    expect(plyAtX(9999, 600, 10)).toBe(10);
    expect(plyAtX(-50, 600, 10)).toBe(0);
    expect(plyAtX(10, 0, 10)).toBe(0);
  });
});

describe("variation", () => {
  it("plays legal moves and rejects illegal ones", () => {
    const v0 = startVariation(0, START);
    const v1 = playMove(v0, "e2", "e4")!;
    expect(v1.sans).toEqual(["e4"]);
    expect(v1.index).toBe(1);
    expect(playMove(v1, "e2", "e4")).toBeNull(); // pawn is no longer there
    expect(playMove(v0, "e2", "e5")).toBeNull(); // pawn cannot jump three squares
  });

  it("never mutates the variation it started from", () => {
    const v0 = startVariation(0, START);
    playMove(v0, "e2", "e4");
    expect(v0.sans).toEqual([]);
    expect(currentFen(v0)).toBe(START);
  });

  it("discards moves after the current index when a new move is played", () => {
    let v = fromSans(0, START, ["e4", "e5", "Nf3"])!;
    v = stepVariation(v, -2); // back to after 1.e4
    const branched = playMove(v, "c7", "c5")!;
    expect(branched.sans).toEqual(["e4", "c5"]);
  });

  it("builds a line from SAN and stops at the first illegal move", () => {
    expect(fromSans(0, START, ["e4", "e5", "Nf3"], 2)!.sans).toEqual(["e4", "e5"]);
    expect(fromSans(0, START, ["e4", "Qh5"])!.sans).toEqual(["e4"]); // Qh5 illegal for Black
    expect(fromSans(0, START, ["Qh5"])).toBeNull();
  });

  it("clamps stepping within the line", () => {
    const v = fromSans(0, START, ["e4", "e5"])!;
    expect(stepVariation(v, 99).index).toBe(2);
    expect(stepVariation(v, -99).index).toBe(0);
  });

  it("numbers variation moves from the base position", () => {
    const afterE4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
    const v = fromSans(1, afterE4, ["e5", "Nf3", "Nc6"])!;
    expect(formatVariation(v).map((m) => m.text)).toEqual(["1... e5", "2. Nf3", "Nc6"]);
  });
});

describe("durationText", () => {
  it.each([
    [3, "a few seconds"],
    [9.9, "a few seconds"],
    [12, "about 10 seconds"],
    [40, "about 40 seconds"],
    [54, "about 55 seconds"],
    [60, "about a minute"],
    [89, "about a minute"],
    [90, "about 1½ minutes"],
    [120, "about 2 minutes"],
    [140, "about 2½ minutes"],
    [290, "about 5 minutes"],
    [600, "about 10 minutes"],
    [1510, "about 25 minutes"],
    [3600, "about 1 h"],
    [4200, "about 1 h 10 min"],
    [7200, "about 2 h"],
  ])("%s s -> %s", (s, text) => {
    expect(durationText(s)).toBe(text);
  });

  it("is empty for nonsense", () => {
    expect(durationText(Number.NaN)).toBe("");
    expect(durationText(-5)).toBe("");
  });
});

describe("runTookText", () => {
  it("shows seconds, then minutes and seconds", () => {
    expect(runTookText("2024-01-01T00:00:00Z", "2024-01-01T00:00:41Z")).toBe("41 s");
    expect(runTookText("2024-01-01T00:00:00Z", "2024-01-01T00:02:05Z")).toBe("2 min 5 s");
    expect(runTookText("2024-01-01T00:00:00Z", "2024-01-01T00:01:00Z")).toBe("1 min 0 s");
  });
  it("is empty while a run is unfinished and never negative", () => {
    expect(runTookText("2024-01-01T00:00:00Z", null)).toBe("");
    expect(runTookText("2024-01-01T00:00:10Z", "2024-01-01T00:00:00Z")).toBe("0 s");
  });
});
