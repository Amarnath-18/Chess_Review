import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PuzzleAnswer, Stats, TrainStatus } from "../api/types";
import { parseTypedMove } from "../components/MoveInput";
import { type Call, mockApi, renderAt } from "../test/render";
import StatsPage from "./StatsPage";
import TrainPage from "./TrainPage";

vi.mock("../components/Board", () => ({
  Board: (p: { fen: string; orientation: string; arrows?: { from: string; to: string }[]; onMove: (f: string, t: string) => boolean }) => (
    <div data-testid="board" data-fen={p.fen} data-orientation={p.orientation} data-arrows={(p.arrows ?? []).map((a) => a.from + a.to).join(",")}>
      <button onClick={() => p.onMove("d2", "d4")}>drop d2d4</button>
      <button onClick={() => p.onMove("e2", "e4")}>drop e2e4</button>
      <button onClick={() => p.onMove("a1", "a8")}>drop illegal</button>
    </div>
  ),
}));

afterEach(() => vi.unstubAllGlobals());

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const sent = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

const status = (over: Partial<TrainStatus> = {}): TrainStatus => ({
  needs_names: false, games_looked_at: 1, new_puzzles: 1, total: 3, due: 2, mastered: 0,
  next: { id: "p1", fen: START, side_to_move: "white", game_id: "g1", ply: 1, box: 1 },
  ...over,
});

const answered = (over: Partial<PuzzleAnswer> = {}): PuzzleAnswer => ({
  correct: false, best_uci: "e2e4", best_san: "e4", played_uci: "a2a3", played_san: "a3",
  line_san: ["e4", "e5", "Nf3"], game_id: "g1", ply: 1, box: 1, due_at: "2024-03-10T00:00:00Z", due: 1, ...over,
});

function serveTrain(t: TrainStatus, answer: PuzzleAnswer = answered()) {
  return mockApi((c) => {
    if (c.url === "/api/train") return { body: t };
    if (c.url === "/api/train/p1/answer") return { body: answer };
  });
}
const openTrain = () => renderAt("/train", [{ path: "/train", element: <TrainPage /> }]);

describe("typed moves", () => {
  it("reads SAN and coordinate moves, and rejects everything else", () => {
    expect(parseTypedMove(START, "Nf3")).toEqual({ from: "g1", to: "f3" });
    expect(parseTypedMove(START, "e2e4")).toEqual({ from: "e2", to: "e4" });
    expect(parseTypedMove(START, " E2E4 ")).toEqual({ from: "e2", to: "e4" });
    expect(parseTypedMove(START, "e5")).toBeNull(); // illegal
    expect(parseTypedMove(START, "hello")).toBeNull();
    expect(parseTypedMove(START, "")).toBeNull();
  });
});

describe("the puzzle trainer", () => {
  it("asks for names when the app cannot tell who you are", async () => {
    serveTrain(status({ needs_names: true, total: 0, due: 0, next: null }));
    openTrain();
    expect(await screen.findByText(/needs to know which player you are/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("explains an empty trainer", async () => {
    serveTrain(status({ total: 0, due: 0, next: null }));
    openTrain();
    expect(await screen.findByTestId("no-puzzles")).toHaveTextContent("Analyze some");
  });

  it("shows the position from the mistaken side without the answer, and reveals it after a miss", async () => {
    const calls = serveTrain(status());
    openTrain();
    const board = await screen.findByTestId("board");
    expect(board).toHaveAttribute("data-fen", START);
    expect(board).toHaveAttribute("data-orientation", "white");
    expect(screen.getByTestId("puzzle-prompt")).toHaveTextContent("Find the move you should have played");
    expect(screen.getByTestId("train-counts")).toHaveTextContent("2 due now · 3 puzzles in all");

    await userEvent.setup().click(screen.getByRole("button", { name: "drop d2d4" }));
    const result = await screen.findByTestId("puzzle-result");
    expect(sent(calls, "/api/train/p1/answer")[0].body).toEqual({ uci: "d2d4" });
    expect(result).toHaveTextContent("Not quite.");
    expect(result).toHaveTextContent("The engine's choice was e4");
    expect(result).toHaveTextContent("In the game you played a3");
    expect(screen.getByRole("link", { name: "Open the game" })).toHaveAttribute("href", "/games/g1");
    expect(screen.getByTestId("board")).toHaveAttribute("data-arrows", "e2e4"); // the answer is drawn
    expect(screen.getByRole("button", { name: "Next puzzle (1 due)" })).toBeInTheDocument();
  });

  it("congratulates a correct answer and does not accept a second one", async () => {
    const calls = serveTrain(status(), answered({ correct: true, box: 2, due: 0 }));
    openTrain();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "drop e2e4" }));
    expect(await screen.findByTestId("puzzle-result")).toHaveTextContent("Correct!");
    expect(screen.getByRole("button", { name: "Finish" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "drop e2e4" }));
    expect(sent(calls, "/api/train/p1/answer")).toHaveLength(1);
  });

  it("ignores an illegal move without asking the server", async () => {
    const calls = serveTrain(status());
    openTrain();
    await userEvent.setup().click(await screen.findByRole("button", { name: "drop illegal" }));
    expect(sent(calls, "/api/train/p1/answer")).toHaveLength(0);
    expect(screen.queryByTestId("puzzle-result")).not.toBeInTheDocument();
  });

  it("can be played from the keyboard by typing the move", async () => {
    const calls = serveTrain(status());
    openTrain();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Type your move"), "d4");
    await user.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() => expect(sent(calls, "/api/train/p1/answer")[0].body).toEqual({ uci: "d2d4" }));
  });

  it("says when everything is done", async () => {
    serveTrain(status({ next: null, due: 0 }));
    openTrain();
    expect(await screen.findByTestId("all-done")).toHaveTextContent("All caught up");
  });
});

// ---- statistics -------------------------------------------------------------------------------

const bucket = (key: string, label: string, moves: number, per100: number | null, reliable: boolean) => ({
  key, label, games: 1, moves, inaccuracies: 1, mistakes: 1, blunders: 1, serious_per_100: per100, reliable,
});

const STATS: Stats = {
  needs_names: false, games_analyzed: 5, games_included: 3, games_unidentified: 2, min_games: 10, min_moves: 30,
  overall: bucket("all", "All moves", 90, 4.4, true),
  by_phase: [bucket("opening", "Opening (first 10 moves)", 20, 0, false), bucket("endgame", "Endgame", 40, 12.5, true)],
  by_color: [], by_time_control: [bucket("blitz", "Blitz", 90, 4.4, true)],
  openings: [
    { name: "Italian Game", games: 12, wins: 6, draws: 1, losses: 5, accuracy: 81.2, reliable: true },
    { name: "Sicilian Defense", games: 2, wins: 0, draws: 0, losses: 2, accuracy: null, reliable: false },
  ],
  trend: [
    { game_id: "a", played_at: "2024-03-01", accuracy: 70, color: "white", opponent: "Bo" },
    { game_id: "b", played_at: "2024-03-02", accuracy: 80, color: "black", opponent: "Cy" },
  ],
  highlights: ["Phase: Endgame stands out, with 12.5 mistakes or blunders per 100 moves against 4.4 overall (40 moves)."],
};
const openStats = (s: Stats) => {
  mockApi((c) => (c.url === "/api/stats" ? { body: s } : undefined));
  renderAt("/stats", [{ path: "/stats", element: <StatsPage /> }]);
};

describe("statistics", () => {
  it("asks for names when the app cannot tell who you are", async () => {
    openStats({ ...STATS, needs_names: true });
    expect(await screen.findByText(/needs to know which player you are/)).toBeInTheDocument();
    expect(screen.queryByTestId("trend")).not.toBeInTheDocument();
  });

  it("states what it is based on, including the games it left out", async () => {
    openStats(STATS);
    const basis = await screen.findByTestId("stats-basis");
    expect(basis).toHaveTextContent("Based on 3 analyzed games");
    expect(basis).toHaveTextContent("90 of your moves");
    expect(basis).toHaveTextContent("2 analyzed games were left out");
    expect(screen.getByTestId("highlights")).toHaveTextContent("Endgame stands out");
  });

  it("greys and labels small samples instead of presenting them as findings", async () => {
    openStats(STATS);
    const opening = await screen.findByTestId("bucket-opening");
    expect(opening).toHaveTextContent("too few moves to conclude");
    expect(opening.className).toContain("text-slate-500");
    expect(screen.getByTestId("bucket-endgame")).not.toHaveTextContent("too few");
    const rows = screen.getAllByTestId("opening-row");
    expect(rows[0]).not.toHaveTextContent("too few");
    expect(rows[1]).toHaveTextContent("too few games");
    expect(rows[1]).toHaveTextContent("–"); // no accuracy figure invented
  });

  it("draws the trend and says what it shows", async () => {
    openStats(STATS);
    const trend = await screen.findByTestId("trend");
    expect(trend).toHaveTextContent("2 games, oldest to newest. Average 75.0%");
    expect(screen.getByRole("img", { name: /from 70% to 80%, average 75%/ })).toBeInTheDocument();
  });

  it("does not claim a weakness when there is not enough data", async () => {
    openStats({ ...STATS, highlights: [] });
    expect(await screen.findByText(/is called a weakness until there is enough data/)).toBeInTheDocument();
  });
});
