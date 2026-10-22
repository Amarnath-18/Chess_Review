import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ClockInfo, MoveClass } from "../api/types";
import { formatClock, moverIsWhite, sideTimes } from "../lib/clocks";
import { ClockPanel } from "./ClockPanel";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

const CLOCKS: ClockInfo[] = [
  { ply: 1, clock: 181, spent: 1, time_trouble: false },
  { ply: 2, clock: 180, spent: 2, time_trouble: false },
  { ply: 3, clock: 170, spent: 13, time_trouble: false },
  { ply: 4, clock: 15, spent: 167, time_trouble: true },
  { ply: 5, clock: 168, spent: 4, time_trouble: false },
  { ply: 6, clock: 9, spent: 8, time_trouble: true },
];
// index = ply; black blunders at ply 4 (in trouble), white blunders at ply 5 (not in trouble)
const CLASSES: (MoveClass | null)[] = [null, "best", "best", "good", "blunder", "blunder", "mistake"];

describe("clock helpers", () => {
  it("formats times, and shows a dash for unknown", () => {
    expect(formatClock(75)).toBe("1:15");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(null)).toBe("–");
  });

  it("knows who moved each ply, including games that start with Black to move", () => {
    expect(moverIsWhite(1, START)).toBe(true);
    expect(moverIsWhite(2, START)).toBe(false);
    expect(moverIsWhite(1, "8/8/8/8/8/8/8/k6K b - - 0 1")).toBe(false);
  });

  it("counts a side's errors made in time trouble", () => {
    const white = sideTimes(CLOCKS, CLASSES, START, true);
    const black = sideTimes(CLOCKS, CLASSES, START, false);
    expect(black).toMatchObject({ errors: 2, errorsInTrouble: 2, troubleMoves: 2 });
    expect(white).toMatchObject({ errors: 1, errorsInTrouble: 0, troubleMoves: 0 });
  });
});

describe("ClockPanel", () => {
  const setup = (analyzed = true) => {
    const classes = analyzed ? CLASSES : undefined;
    const onSelect = vi.fn();
    render(
      <ClockPanel
        clocks={CLOCKS}
        startFen={START}
        classes={classes}
        white="Alice"
        black="Bob"
        currentPly={3}
        onSelect={onSelect}
        moveLabel={(p) => `move ${p}`}
      />,
    );
    return onSelect;
  };

  it("shows averages and time-trouble counts per side", () => {
    setup();
    expect(screen.getByTestId("avg-white")).toHaveTextContent("0:06"); // (1 + 13 + 4) / 3
    expect(screen.getByTestId("avg-black")).toHaveTextContent("0:59"); // (2 + 167 + 8) / 3
    expect(screen.getByTestId("trouble-black")).toHaveTextContent("2");
    expect(screen.getByTestId("trouble-white")).toHaveTextContent("0");
  });

  it("says how the clock relates to mistakes, for each side", () => {
    setup();
    const insights = screen.getByTestId("clock-insights");
    expect(insights).toHaveTextContent("2 of Bob's 2 mistakes or blunders came in time trouble.");
    expect(insights).toHaveTextContent("None of Alice's 1 mistake or blunder came in time trouble.");
  });

  it("without an analysis there are no claims about mistakes", () => {
    setup(false);
    expect(screen.queryByTestId("clock-insights")).not.toBeInTheDocument();
    expect(screen.getByText(/Analyze the game to see how the clock relates/)).toBeInTheDocument();
  });

  it("reads out the current move's clock and time taken", () => {
    setup();
    expect(screen.getByTestId("clock-readout")).toHaveTextContent("move 3 · 2:50 left · took 0:13");
  });

  it("jumps to the longest think", async () => {
    const onSelect = setup();
    await userEvent.setup().click(screen.getByRole("button", { name: "2:47" }));
    expect(onSelect).toHaveBeenCalledWith(4);
  });
});
