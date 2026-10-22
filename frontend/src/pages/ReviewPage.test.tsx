import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GAME_ID, makeAnalysis, makeGame, makeJob } from "../test/fixtures";
import { mockApi, renderReview, type Call } from "../test/render";

// The real chessboard needs layout APIs jsdom lacks; a stand-in exposes the same props.
vi.mock("../components/Board", () => ({
  Board: (p: {
    fen: string;
    arrows?: { from: string; to: string; color: string }[];
    mark?: { square: string; cls: string } | null;
    lastMove?: [string, string] | null;
    onMove: (f: string, t: string) => boolean;
  }) => (
    <div
      data-testid="board"
      data-fen={p.fen}
      data-arrows={(p.arrows ?? []).map((a) => a.from + a.to).join(",")}
      data-mark={p.mark ? `${p.mark.square}:${p.mark.cls}` : ""}
      data-last={p.lastMove?.join("") ?? ""}
    >
      <button onClick={() => p.onMove("g1", "f3")}>drop g1f3</button>
      <button onClick={() => p.onMove("a1", "a8")}>drop illegal</button>
    </div>
  ),
}));

const game = makeGame();
const analysis = makeAnalysis();
const fenAt = (ply: number) => (ply === 0 ? game.start_fen : game.moves[ply - 1].fen);
const boardFen = () => screen.getByTestId("board").getAttribute("data-fen");

function analyzedApi() {
  return mockApi((c) => {
    if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ has_analysis: true, analysis_status: "completed" }) };
    if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: analysis };
  });
}

async function openAnalyzed() {
  const calls = analyzedApi();
  renderReview(GAME_ID);
  await screen.findByTestId("board");
  await screen.findByTestId("engine-panel");
  return calls;
}

const mutations = (calls: Call[]) =>
  calls.filter((c) => c.method !== "GET" && c.url !== "/api/session");

beforeEach(() => {
  // desktop layout
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: q.includes("min-width"),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("navigation (AT-05)", () => {
  it("shows the start position, then follows next / prev / first / last", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    expect(boardFen()).toBe(fenAt(0));

    await user.click(screen.getByRole("button", { name: "Next move" }));
    expect(boardFen()).toBe(fenAt(1));
    await user.click(screen.getByRole("button", { name: "Last move" }));
    expect(boardFen()).toBe(fenAt(6));
    await user.click(screen.getByRole("button", { name: "Previous move" }));
    expect(boardFen()).toBe(fenAt(5));
    await user.click(screen.getByRole("button", { name: "First move" }));
    expect(boardFen()).toBe(fenAt(0));
  });

  it("supports the keyboard", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(boardFen()).toBe(fenAt(3));
    await user.keyboard("{ArrowLeft}");
    expect(boardFen()).toBe(fenAt(2));
    await user.keyboard("{End}");
    expect(boardFen()).toBe(fenAt(6));
    await user.keyboard("{Home}");
    expect(boardFen()).toBe(fenAt(0));
  });

  it("does not hijack keys while typing in a field", async () => {
    await openAnalyzed();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(boardFen()).toBe(fenAt(0));
    input.remove();
  });

  it("selecting any move in the list shows its position and highlights it", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    for (const ply of [4, 1, 6, 3]) {
      const san = game.moves[ply - 1].san;
      const list = screen.getByRole("group", { name: "Moves" });
      await user.click(within(list).getByRole("button", { name: new RegExp(`^${san}`) }));
      expect(boardFen()).toBe(fenAt(ply));
      expect(screen.getByTestId("board").getAttribute("data-last")).toBe(game.moves[ply - 1].uci);
    }
    expect(screen.getByTestId("current-move")).toHaveTextContent("2. Nf3");
  });

  it("can flip the board with F", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    expect(screen.getByTestId("player-black").compareDocumentPosition(screen.getByTestId("player-white")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.keyboard("f");
    expect(screen.getByTestId("player-white").compareDocumentPosition(screen.getByTestId("player-black")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("evaluation graph (AT-06)", () => {
  it("selects the move nearest to the clicked point and stays in sync", async () => {
    await openAnalyzed();
    const svg = screen.getByTestId("eval-graph");
    svg.getBoundingClientRect = () => ({ left: 100, width: 600, top: 0, height: 140, right: 700, bottom: 140, x: 100, y: 0, toJSON() {} });

    fireEvent.click(svg, { clientX: 100 + 300 }); // middle of 6 plies = ply 3
    expect(boardFen()).toBe(fenAt(3));
    expect(screen.getByTestId("graph-cursor").getAttribute("data-ply")).toBe("3");

    fireEvent.click(svg, { clientX: 100 + 600 }); // far right = last ply
    expect(boardFen()).toBe(fenAt(6));
    fireEvent.click(svg, { clientX: 100 - 40 }); // left of the plot clamps to start
    expect(boardFen()).toBe(fenAt(0));
  });

  it("moving through the game moves the graph cursor", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(screen.getByTestId("graph-cursor").getAttribute("data-ply")).toBe("2");
  });
});

describe("review content", () => {
  it("shows the engine's evaluation, best-move arrow and played-move verdict", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    expect(screen.getByTestId("engine-eval")).toHaveTextContent("+0.20");
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("e2e4,d2d4,g1f3");

    await user.keyboard("{End}{ArrowLeft}"); // ply 5: the blunder
    const played = screen.getByTestId("played-move");
    expect(played).toHaveTextContent("Played Bc4");
    expect(played).toHaveTextContent("Blunder");
    expect(played).toHaveTextContent("Miss: a win was available");
    expect(played).toHaveTextContent("33.3");
  });

  it("summary counts come straight from the saved classifications", async () => {
    await openAnalyzed();
    expect(screen.getByTestId("count-white-blunder")).toHaveTextContent("1");
    expect(screen.getByTestId("count-white-great")).toHaveTextContent("1");
    expect(screen.getByTestId("count-white-excellent")).toHaveTextContent("1");
    expect(screen.getByTestId("count-black-best")).toHaveTextContent("2");
    expect(screen.getByTestId("count-black-good")).toHaveTextContent("1");
    expect(screen.getByText("Analysis complete")).toBeInTheDocument();
  });

  it("jumps to a key position from the summary", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /3\. Bc4/ , description: undefined }));
    expect(boardFen()).toBe(fenAt(5));
  });

  it("shows an unavailable evaluation as n/a, never as a draw", async () => {
    const a = makeAnalysis();
    a.positions[0].eval = { cp: null, mate: null, terminal_result: null, display: null, win_pct: null };
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ has_analysis: true, analysis_status: "completed" }) };
      if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: a };
    });
    renderReview(GAME_ID);
    await screen.findByTestId("engine-panel");
    expect(screen.getByTestId("engine-eval")).toHaveTextContent("n/a");
    expect(screen.getByTestId("engine-eval")).not.toHaveTextContent("0.00");
    expect(screen.getByText(/has no evaluation/)).toBeInTheDocument();
  });
});

describe("several engine lines", () => {
  it("shows three lines by default, each with its own evaluation, and arrows for each", async () => {
    await openAnalyzed();
    const lines = screen.getByTestId("engine-lines");
    expect(within(lines).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByTestId("engine-line-1")).toHaveTextContent("+0.20");
    expect(screen.getByTestId("engine-line-2")).toHaveTextContent("-0.05"); // 25 cp worse each rank
    expect(screen.getByTestId("engine-line-3")).toHaveTextContent("-0.30");
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("e2e4,d2d4,g1f3");
  });

  it("lets the user choose how many lines to see, for the list and the arrows", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    const control = screen.getByRole("group", { name: "Engine lines shown" });

    await user.click(within(control).getByRole("button", { name: "1" }));
    expect(within(screen.getByTestId("engine-lines")).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("e2e4");

    await user.click(within(control).getByRole("button", { name: "2" }));
    expect(within(screen.getByTestId("engine-lines")).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("e2e4,d2d4");

    // only 3 lines exist in this analysis, so there is nothing to choose beyond 3
    expect(within(control).queryByRole("button", { name: "4" })).toBeNull();
    expect(within(control).queryByRole("button", { name: "5" })).toBeNull();
  });

  it("offers no more lines than the analysis contains", async () => {
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ has_analysis: true, analysis_status: "completed" }) };
      if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: makeAnalysis(2) };
    });
    renderReview(GAME_ID);
    await screen.findByTestId("engine-panel");
    const control = screen.getByRole("group", { name: "Engine lines shown" });
    expect(within(control).getAllByRole("button").map((b) => b.textContent)).toEqual(["1", "2"]);
    expect(within(screen.getByTestId("engine-lines")).getAllByRole("listitem")).toHaveLength(2);
  });

  it("hides the control when only one line was analyzed", async () => {
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ has_analysis: true, analysis_status: "completed" }) };
      if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: makeAnalysis(1) };
    });
    renderReview(GAME_ID);
    await screen.findByTestId("engine-panel");
    expect(screen.queryByRole("group", { name: "Engine lines shown" })).toBeNull();
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("e2e4");
  });

  it("can hide the arrows", async () => {
    await openAnalyzed();
    await userEvent.setup().click(screen.getByLabelText("Show engine arrows"));
    expect(screen.getByTestId("board").getAttribute("data-arrows")).toBe("");
  });

  it("playing an engine line from the list starts a local variation", async () => {
    const calls = await openAnalyzed();
    const user = userEvent.setup();
    await user.click(within(screen.getByRole("group", { name: /^Line 2/ })).getByRole("button", { name: "d4" }));
    expect(screen.getByTestId("variation-banner")).toHaveTextContent("1. d4");
    expect(mutations(calls)).toEqual([]);
  });
});

describe("move marks on the board", () => {
  const expected: Record<number, string> = {
    1: "e4:great",
    2: "e5:best",
    3: "f3:excellent",
    4: "c6:good",
    5: "c4:blunder",
    6: "f6:best",
  };

  it("marks the destination square of every move with its quality", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    const board = () => screen.getByTestId("board");
    expect(board().getAttribute("data-mark")).toBe(""); // start position: no move yet
    for (let ply = 1; ply <= 6; ply++) {
      await user.keyboard("{ArrowRight}");
      expect(board().getAttribute("data-mark")).toBe(expected[ply]);
    }
  });

  it("shows no mark while exploring a variation", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.keyboard("{ArrowRight}{ArrowRight}"); // after 1...e5, White to move: g1f3 is legal
    expect(screen.getByTestId("board").getAttribute("data-mark")).toBe("e5:best");
    await user.click(screen.getByRole("button", { name: "drop g1f3" }));
    expect(screen.getByTestId("variation-banner")).toBeInTheDocument();
    expect(screen.getByTestId("board").getAttribute("data-mark")).toBe("");
  });

  it("marks every move in the move list, not just the notable ones", async () => {
    await openAnalyzed();
    const list = screen.getByRole("group", { name: "Moves" });
    const classes = Array.from(list.querySelectorAll("[data-class]")).map((e) => e.getAttribute("data-class"));
    expect(classes).toEqual(["great", "best", "excellent", "good", "blunder", "best"]);
    const glyphs = Array.from(list.querySelectorAll("[data-class]")).map((e) => e.textContent);
    expect(glyphs).toEqual(["!", "★", "✓", "○", "??", "★"]);
  });

  it("does not mark moves of a game that has not been analyzed", async () => {
    mockApi((c) => (c.url === `/api/games/${GAME_ID}` ? { body: game } : undefined));
    renderReview(GAME_ID);
    await screen.findByTestId("board");
    await userEvent.setup().keyboard("{ArrowRight}");
    expect(screen.getByTestId("board").getAttribute("data-mark")).toBe("");
    expect(screen.getByRole("group", { name: "Moves" }).querySelectorAll("[data-class]")).toHaveLength(0);
  });
});

describe("variations never touch the saved game", () => {
  it("exploring the engine line leaves the game position and the server untouched", async () => {
    const calls = await openAnalyzed();
    const user = userEvent.setup();

    const line = screen.getByRole("group", { name: /^Line 1/ });
    await user.click(within(line).getByRole("button", { name: "e5" }));
    const banner = screen.getByTestId("variation-banner");
    expect(banner).toHaveTextContent("not saved");
    expect(boardFen()).not.toBe(fenAt(0));
    expect(banner).toHaveTextContent("1. e4");

    await user.click(within(banner).getByRole("button", { name: /Return to game/ }));
    expect(screen.queryByTestId("variation-banner")).toBeNull();
    expect(boardFen()).toBe(fenAt(0));
    expect(mutations(calls)).toEqual([]); // nothing was sent to the server
  });

  it("dragging a piece starts a local variation; illegal drops are refused; Esc returns", async () => {
    const calls = await openAnalyzed();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "drop illegal" }));
    expect(screen.queryByTestId("variation-banner")).toBeNull();

    await user.click(screen.getByRole("button", { name: "drop g1f3" }));
    expect(screen.getByTestId("variation-banner")).toBeInTheDocument();
    expect(boardFen()).toContain("5N2"); // knight on f3

    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("variation-banner")).toBeNull();
    expect(boardFen()).toBe(fenAt(0));
    expect(mutations(calls)).toEqual([]);
    expect(analysis.positions[0].fen).toBe(fenAt(0)); // saved analysis object unchanged
  });

  it("arrow keys step inside a variation and ← at its start returns to the game", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "drop g1f3" }));
    const inVariation = boardFen();
    await user.keyboard("{ArrowLeft}");
    expect(boardFen()).toBe(fenAt(0));
    expect(screen.getByTestId("variation-banner")).toBeInTheDocument(); // index 0 of the variation
    await user.keyboard("{ArrowRight}");
    expect(boardFen()).toBe(inVariation);
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.queryByTestId("variation-banner")).toBeNull();
  });

  it("selecting a game move while exploring discards the variation", async () => {
    await openAnalyzed();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "drop g1f3" }));
    await user.click(within(screen.getByRole("group", { name: "Moves" })).getByRole("button", { name: /^e5/ }));
    expect(screen.queryByTestId("variation-banner")).toBeNull();
    expect(boardFen()).toBe(fenAt(2));
  });
});

describe("analysis jobs", () => {
  it("offers to analyze an un-analyzed game and sends the chosen depth", async () => {
    const calls = mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: game };
      if (c.method === "POST" && c.url === `/api/games/${GAME_ID}/analysis`)
        return { status: 202, body: { cached: false, job: makeJob(), run_id: null } };
    });
    renderReview(GAME_ID);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Search depth"), "20");
    expect(screen.getByLabelText("Engine lines")).toHaveValue("3"); // sensible default
    await user.selectOptions(screen.getByLabelText("Engine lines"), "5");
    await user.click(screen.getByRole("button", { name: "Analyze game" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/analysis"))).toBe(true));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/analysis"))!.body).toEqual({
      depth: 20,
      multipv: 5,
    });
    expect(screen.getByText(/has not been analyzed yet|Waiting|Analyzing/)).toBeInTheDocument();
  });

  it("shows live progress while the job runs", async () => {
    const running = makeJob({ status: "running", progress_done: 3, progress_total: 7 });
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ analysis_status: "running", latest_job: running }) };
      if (c.url === `/api/jobs/${running.id}`) return { body: running };
    });
    renderReview(GAME_ID);
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "43");
    expect(screen.getByText("3/7 positions")).toBeInTheDocument();
    // the board is usable while waiting
    await userEvent.setup().keyboard("{ArrowRight}");
    expect(boardFen()).toBe(fenAt(1));
  });

  it("explains a failed job, keeps the old review, and can retry", async () => {
    const failed = makeJob({ status: "failed", error: "The analysis engine failed: engine died" });
    const calls = mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`)
        return { body: makeGame({ has_analysis: true, analysis_status: "completed", latest_job: failed }) };
      if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: analysis };
      if (c.method === "POST" && c.url === `/api/jobs/${failed.id}/retry`)
        return { status: 202, body: { cached: false, job: makeJob({ id: "new" }), run_id: null } };
    });
    renderReview(GAME_ID);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("engine died");
    expect(await screen.findByTestId("engine-panel")).toBeInTheDocument(); // old review still shown
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("earlier review is unchanged"));

    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/retry"))).toBe(true));
  });
});

describe("errors", () => {
  it("shows a friendly message for a game that is not found", async () => {
    mockApi((c) => (c.url.startsWith("/api/games/") ? { status: 404, body: { detail: "Game not found" } } : undefined));
    renderReview("nope");
    expect(await screen.findByText("Game not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to your games/ })).toBeInTheDocument();
  });
});

describe("saved defaults", () => {
  const prefs = {
    default_depth: 12,
    default_multipv: 2,
    import_count: 20,
    max_depth: 22,
    max_multipv: 5,
    retention_days: 30,
  };

  it("pre-fill the analysis form for a game that has not been analyzed", async () => {
    const calls = mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: game };
      if (c.url === "/api/settings") return { body: prefs };
      if (c.method === "POST" && c.url.endsWith("/analysis"))
        return { status: 202, body: { cached: false, job: makeJob(), run_id: null } };
    });
    renderReview(GAME_ID);
    const depth = await screen.findByLabelText("Search depth");
    await waitFor(() => expect(depth).toHaveValue("12")); // once the saved settings have loaded
    expect(screen.getByLabelText("Engine lines")).toHaveValue("2");

    await userEvent.setup().click(screen.getByRole("button", { name: "Analyze game" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ depth: 12, multipv: 2 });
  });

  it("do not override what an existing review used", async () => {
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`)
        return { body: makeGame({ has_analysis: true, analysis_status: "completed" }) };
      if (c.url === `/api/games/${GAME_ID}/analysis`) return { body: analysis };
      if (c.url === "/api/settings") return { body: prefs };
    });
    renderReview(GAME_ID);
    await screen.findByTestId("engine-panel");
    await userEvent.setup().click(screen.getByRole("button", { name: /Different settings/ }));
    // the review was made at depth 16 with 3 lines; the form starts from that, not from the defaults
    expect(screen.getByLabelText("Search depth")).toHaveValue("16");
    expect(screen.getByLabelText("Engine lines")).toHaveValue("3");
  });

  it("fall back to sensible values when settings cannot be loaded", async () => {
    mockApi((c) => (c.url === `/api/games/${GAME_ID}` ? { body: game } : undefined));
    renderReview(GAME_ID);
    expect(await screen.findByLabelText("Search depth")).toHaveValue("16");
    expect(screen.getByLabelText("Engine lines")).toHaveValue("3");
  });

  it("limit the engine-line choices to what the server allows", async () => {
    mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: game };
      if (c.url === "/api/settings") return { body: { ...prefs, max_multipv: 3 } };
    });
    renderReview(GAME_ID);
    const select = await screen.findByLabelText("Engine lines");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
  });

  it("can still be overridden for one game", async () => {
    const calls = mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: game };
      if (c.url === "/api/settings") return { body: prefs };
      if (c.method === "POST" && c.url.endsWith("/analysis"))
        return { status: 202, body: { cached: false, job: makeJob(), run_id: null } };
    });
    renderReview(GAME_ID);
    const user = userEvent.setup();
    const depth = await screen.findByLabelText("Search depth");
    await waitFor(() => expect(screen.getByLabelText("Engine lines")).toHaveValue("2")); // settings loaded
    await user.selectOptions(depth, "20");
    await user.click(screen.getByRole("button", { name: "Analyze game" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ depth: 20, multipv: 2 });
  });
});

describe("time estimate", () => {
  const est = (over: object = {}) => ({
    seconds: 95,
    seconds_low: 38,
    seconds_high: 240,
    positions: 7,
    limit_seconds: 600,
    exceeds_limit: false,
    may_exceed_limit: false,
    calibrated_from_runs: 0,
    ...over,
  });

  function serve(estimate: (c: Call) => { status?: number; body?: unknown } | undefined) {
    return mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: game };
      if (c.url.startsWith(`/api/games/${GAME_ID}/analysis/estimate`)) return estimate(c);
      if (c.method === "POST" && c.url.endsWith("/analysis"))
        return { status: 202, body: { cached: false, job: makeJob(), run_id: null } };
    });
  }

  it("is shown before you start, as a rough guide", async () => {
    serve(() => ({ body: est() }));
    renderReview(GAME_ID);
    const text = await screen.findByTestId("estimate");
    expect(text).toHaveTextContent("Estimated time: about 1½ minutes, possibly up to 4 minutes");
    expect(text).toHaveTextContent("rough guide");
  });

  it("asks the server for the chosen depth and number of lines, and updates when they change", async () => {
    const calls = serve((c) => ({ body: est({ seconds: new URL(c.url, "http://x").searchParams.get("depth") === "20" ? 700 : 40, seconds_high: 1000 }) }));
    renderReview(GAME_ID);
    expect(await screen.findByTestId("estimate")).toHaveTextContent("about 40 seconds");
    const asked = calls.filter((c) => c.url.includes("/analysis/estimate")).at(-1)!;
    expect(Object.fromEntries(new URL(asked.url, "http://x").searchParams)).toEqual({ depth: "16", multipv: "3" });

    await userEvent.setup().selectOptions(screen.getByLabelText("Search depth"), "20");
    await waitFor(() => expect(screen.getByTestId("estimate")).toHaveTextContent("about 12 minutes"));
    const latest = calls.filter((c) => c.url.includes("/analysis/estimate")).at(-1)!;
    expect(new URL(latest.url, "http://x").searchParams.get("depth")).toBe("20");
  });

  it("warns, and stops you starting, when the run would exceed the time limit", async () => {
    serve(() => ({ body: est({ seconds: 2400, seconds_high: 6000, limit_seconds: 1500, exceeds_limit: true, may_exceed_limit: true }) }));
    renderReview(GAME_ID);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("longer than the 25 minutes limit");
    expect(alert).toHaveTextContent("lower depth or fewer lines");
    expect(screen.getByRole("button", { name: "Analyze game" })).toBeDisabled();
  });

  it("only cautions you, without blocking, when the slow end of the range might exceed the limit", async () => {
    serve(() => ({
      body: est({ seconds: 900, seconds_high: 2250, limit_seconds: 1500, may_exceed_limit: true }),
    }));
    renderReview(GAME_ID);
    const warning = await screen.findByTestId("estimate-warning");
    expect(warning).toHaveTextContent("might take longer than the 25 minutes limit");
    expect(warning).toHaveTextContent("A lower depth or fewer lines is safer");
    expect(screen.queryByRole("alert")).toBeNull(); // a caution, not an error
    expect(screen.getByRole("button", { name: "Analyze game" })).toBeEnabled();
  });

  it("does not stop you when the run is within the limit", async () => {
    serve(() => ({ body: est() }));
    renderReview(GAME_ID);
    await screen.findByTestId("estimate");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Analyze game" })).toBeEnabled();
  });

  it("shows nothing for a search that cannot be estimated", async () => {
    serve(() => ({ body: est({ seconds: null, seconds_low: null, seconds_high: null }) }));
    renderReview(GAME_ID);
    await screen.findByLabelText("Search depth");
    await waitFor(() => expect(screen.queryByTestId("estimate")).toBeNull());
    expect(screen.getByRole("button", { name: "Analyze game" })).toBeEnabled();
  });

  it("is only a hint: if it fails, analysis still works", async () => {
    const calls = serve(() => ({ status: 500, body: { detail: "boom" } }));
    renderReview(GAME_ID);
    const button = await screen.findByRole("button", { name: "Analyze game" });
    expect(screen.queryByTestId("estimate")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.setup().click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("is not requested while an analysis is already running", async () => {
    const running = makeJob({ status: "running", progress_done: 2, progress_total: 7 });
    const calls = mockApi((c) => {
      if (c.url === `/api/games/${GAME_ID}`) return { body: makeGame({ analysis_status: "running", latest_job: running }) };
      if (c.url === `/api/jobs/${running.id}`) return { body: running };
    });
    renderReview(GAME_ID);
    await screen.findByRole("progressbar");
    expect(calls.filter((c) => c.url.includes("/analysis/estimate"))).toEqual([]);
  });
});

describe("how long a finished review took", () => {
  it("is shown next to the engine settings", async () => {
    await openAnalyzed();
    // the fixture's run started at 00:00:00 and finished at 00:01:00
    expect(screen.getByText(/took 1 min 0 s/)).toBeInTheDocument();
  });
});
