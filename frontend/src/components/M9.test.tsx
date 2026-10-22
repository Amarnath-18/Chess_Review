import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Batch, BatchEstimate, LinkedSource, NewGames } from "../api/types";
import { GAME_ID, makeGame } from "../test/fixtures";
import { type Call, mockApi, renderAt } from "../test/render";
import { BatchPanel, batchRequestFor } from "./BatchPanel";
import { GameNotes } from "./GameNotes";
import { SavedAccounts } from "./SavedAccounts";

afterEach(() => vi.unstubAllGlobals());

const sent = (calls: Call[], method: string, url: string) =>
  calls.filter((c) => c.method === method && c.url === url);

// ---- analyze all ---------------------------------------------------------------------------

const ESTIMATE: BatchEstimate = {
  games: 7,
  skipped: 1,
  positions: 560,
  seconds: 300,
  seconds_low: 120,
  seconds_high: 750,
  too_many: false,
  max_games: 100,
  calibrated_from_runs: 4,
};

const batch = (over: Partial<Batch> = {}): Batch => ({
  id: "b1",
  status: "running",
  params: { depth: 16, multipv: 3 },
  created_at: "2024-03-10T00:00:00Z",
  finished_at: null,
  total: 4,
  counts: { pending: 1, queued: 1, done: 2, failed: 0, skipped: 0, cancelled: 0 },
  items: [
    { game_id: "g1", white: "Ann", black: "Bo", state: "done", message: null, progress_done: null, progress_total: null },
    { game_id: "g2", white: "Cy", black: "Di", state: "queued", message: null, progress_done: 30, progress_total: 80 },
  ],
  ...over,
});

function serveBatch(latest: Batch | null, estimate: BatchEstimate = ESTIMATE) {
  return mockApi((c) => {
    if (c.url === "/api/analysis/batches/latest") return { body: latest };
    if (c.url === "/api/analysis/batches/estimate") return { body: estimate };
    if (c.url === "/api/settings") return { body: { default_depth: 16, default_multipv: 3, import_count: 20, max_depth: 22, max_multipv: 5, retention_days: 30 } };
    if (c.url === "/api/analysis/batches" && c.method === "POST") return { status: 201, body: batch() };
    if (c.url === "/api/analysis/batches/b1/cancel") return { body: batch({ status: "cancelled", counts: { pending: 0, queued: 0, done: 2, failed: 0, skipped: 0, cancelled: 2 } }) };
  });
}

const renderPanel = (query = {}) =>
  renderAt("/games", [{ path: "/games", element: <BatchPanel query={query} /> }]);

describe("analyze all", () => {
  it("turns the history filters into a batch request", () => {
    expect(batchRequestFor({ q: " ann ", source: "lichess", from: "2024-01-01", favorite: true, tag: "study" })).toEqual({
      filter: { q: "ann", source: "lichess", date_from: "2024-01-01", favorite: true, tag: "study" },
      only_unanalyzed: true,
    });
  });

  it("says how many games and how long, then starts the batch", async () => {
    const calls = serveBatch(null);
    renderPanel({ tag: "study" });
    const est = await screen.findByTestId("batch-estimate");
    expect(est).toHaveTextContent("7 games without a review");
    expect(est).toHaveTextContent("possibly up to");
    expect(est).toHaveTextContent("1 cannot be analyzed");
    await userEvent.setup().click(screen.getByRole("button", { name: "Analyze 7 games" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/analysis/batches")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/analysis/batches")[0].body).toEqual({
      filter: { tag: "study" },
      only_unanalyzed: true,
    });
  });

  it("shows nothing when every game already has a review", async () => {
    serveBatch(null, { ...ESTIMATE, games: 0, skipped: 0, positions: 0, seconds: 0, seconds_low: 0, seconds_high: 0 });
    renderPanel();
    await waitFor(() => expect(screen.queryByTestId("batch-estimate")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Analyze/ })).not.toBeInTheDocument();
  });

  it("refuses to start more games than one batch may hold", async () => {
    serveBatch(null, { ...ESTIMATE, too_many: true });
    renderPanel();
    expect(await screen.findByTestId("batch-estimate")).toHaveTextContent("limit is 100");
    expect(screen.getByRole("button", { name: /Analyze 7 games/ })).toBeDisabled();
  });

  it("shows progress while running, and cancels", async () => {
    const calls = serveBatch(batch());
    renderPanel();
    const running = await screen.findByTestId("batch-running");
    expect(running).toHaveTextContent("2 of 4 done");
    expect(running).toHaveTextContent("Now: Cy vs Di (30/80 positions)");
    expect(screen.getByRole("progressbar", { name: "Games analyzed" })).toHaveAttribute("aria-valuenow", "50");
    await userEvent.setup().click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/analysis/batches/b1/cancel")).toHaveLength(1));
    expect(await screen.findByTestId("batch-finished")).toHaveTextContent("Batch cancelled");
  });

  it("reports what failed or was skipped when it finishes, and can be dismissed", async () => {
    serveBatch(
      batch({
        status: "completed",
        counts: { pending: 0, queued: 0, done: 1, failed: 1, skipped: 1, cancelled: 0 },
        items: [
          { game_id: "g1", white: "Ann", black: "Bo", state: "failed", message: "engine error", progress_done: null, progress_total: null },
          { game_id: "g2", white: "Cy", black: "Di", state: "skipped", message: "Too long", progress_done: null, progress_total: null },
        ],
      }),
      { ...ESTIMATE, games: 0 },
    );
    renderPanel();
    const done = await screen.findByTestId("batch-finished");
    expect(done).toHaveTextContent("1 analyzed, 1 failed, 1 skipped");
    expect(done).toHaveTextContent("Ann vs Bo: failed (engine error)");
    expect(done).toHaveTextContent("Cy vs Di: skipped (Too long)");
    await userEvent.setup().click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("batch-finished")).not.toBeInTheDocument();
  });
});

// ---- notes, tags, favourites ------------------------------------------------------------------

function serveGame(over = {}) {
  let game = makeGame({ favorite: false, tags: [], note: null, move_notes: {}, ...over });
  const calls = mockApi((c) => {
    if (c.url === `/api/games/${GAME_ID}` && c.method === "PATCH") {
      const p = c.body as { favorite?: boolean; note?: string; tags?: string[] };
      game = {
        ...game,
        ...(p.favorite !== undefined && { favorite: p.favorite }),
        ...(p.note !== undefined && { note: p.note.trim() || null }),
        ...(p.tags && { tags: [...new Set(p.tags.map((t) => t.trim().toLowerCase()))].sort() }),
      };
      return { body: game };
    }
    const m = c.url.match(new RegExp(`^/api/games/${GAME_ID}/notes/(\\d+)$`));
    if (m && c.method === "PUT") {
      const text = (c.body as { text: string }).text.trim();
      const notes = { ...(game.move_notes ?? {}) };
      if (text) notes[m[1]] = text;
      else delete notes[m[1]];
      game = { ...game, move_notes: notes };
      return { body: game };
    }
  });
  return { calls, game: () => game };
}

function Notes({ ply }: { ply: number }) {
  // re-reads the game from the query cache the way the review page does
  return <GameNotes game={makeGame({ favorite: false, tags: ["italian"], note: "Saved note", move_notes: { "3": "On move 3" } })} ply={ply} moveLabel={(p) => `move ${p}`} />;
}

describe("notes, tags and favourite", () => {
  it("toggles the favourite mark", async () => {
    const { calls } = serveGame();
    renderAt("/", [{ path: "/", element: <Notes ply={0} /> }]);
    const star = screen.getByRole("button", { name: /Mark as favourite/ });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await userEvent.setup().click(star);
    await waitFor(() => expect(sent(calls, "PATCH", `/api/games/${GAME_ID}`)[0].body).toEqual({ favorite: true }));
  });

  it("adds a tag, and removes one", async () => {
    const { calls } = serveGame();
    renderAt("/", [{ path: "/", element: <Notes ply={0} /> }]);
    const user = userEvent.setup();
    expect(screen.getByRole("list", { name: "Tags on this game" })).toHaveTextContent("italian");
    await user.type(screen.getByLabelText("New tag"), "Endgame{enter}");
    await waitFor(() => expect(sent(calls, "PATCH", `/api/games/${GAME_ID}`)[0].body).toEqual({ tags: ["italian", "Endgame"] }));
    await user.click(screen.getByRole("button", { name: "Remove tag italian" }));
    await waitFor(() => expect(sent(calls, "PATCH", `/api/games/${GAME_ID}`)[1].body).toEqual({ tags: [] }));
  });

  it("saves the game note only when asked, and shows when it is unchanged", async () => {
    const { calls } = serveGame();
    renderAt("/", [{ path: "/", element: <Notes ply={0} /> }]);
    const user = userEvent.setup();
    const box = screen.getByTestId("game-note");
    expect(box).toHaveValue("Saved note");
    const save = screen.getAllByRole("button", { name: "Saved" })[0];
    expect(save).toBeDisabled();
    await user.type(box, " and more");
    expect(sent(calls, "PATCH", `/api/games/${GAME_ID}`)).toHaveLength(0); // typing sends nothing
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(calls, "PATCH", `/api/games/${GAME_ID}`)[0].body).toEqual({ note: "Saved note and more" }));
  });

  it("edits the note of the selected move, and asks to select one when at the start", async () => {
    const { calls } = serveGame();
    const first = renderAt("/", [{ path: "/", element: <Notes ply={0} /> }]);
    expect(screen.getByText("Select a move to add a note to it.")).toBeInTheDocument();
    first.unmount();

    renderAt("/", [{ path: "/", element: <Notes ply={3} /> }]);
    const box = screen.getByTestId("move-note");
    expect(screen.getByText("Note on move 3")).toBeInTheDocument();
    expect(box).toHaveValue("On move 3");
    const user = userEvent.setup();
    await user.clear(box);
    await user.type(box, "Better: d4");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(sent(calls, "PUT", `/api/games/${GAME_ID}/notes/3`)[0].body).toEqual({ text: "Better: d4" }));
  });
});

// ---- remembered accounts ---------------------------------------------------------------------

const SOURCE: LinkedSource = {
  id: "s1",
  source: "lichess",
  username: "DrNykterstein",
  created_at: "2024-03-10T00:00:00Z",
  last_checked_at: null,
};

const newGame = (id: string) => ({
  external_id: id, url: null, white: "DrNykterstein", black: "Carl", white_elo: 2800, black_elo: 2790,
  result: "1-0", played_at: "2024-03-09", time_control: "180+0", opening_name: null, ply_count: 40,
  already_imported: false, importable: true, problem: null,
});

function serveSources(found: Partial<NewGames> = {}) {
  return mockApi((c) => {
    if (c.url === "/api/sources" && c.method === "GET") return { body: [SOURCE] };
    if (c.url === "/api/sources/s1/check") {
      return {
        body: { source_id: "s1", source: "lichess", username: "DrNykterstein", new_games: [newGame("aaaaaaaa"), newGame("bbbbbbbb")], checked: 20, already_saved: 18, cannot_import: 0, note: null, skipped_archives: 0, ...found },
      };
    }
    if (c.url === "/api/imports/commit") {
      return { body: { imported: [makeGame()], duplicates: [], errors: [], auto_analyzing: 2 } };
    }
    if (c.url === "/api/sources/s1" && c.method === "DELETE") return { status: 204, body: undefined };
  });
}

describe("saved accounts", () => {
  it("shows nothing until an account is remembered", async () => {
    mockApi((c) => (c.url === "/api/sources" ? { body: [] } : undefined));
    renderAt("/", [{ path: "/", element: <SavedAccounts /> }]);
    await waitFor(() => expect(screen.queryByText("Your accounts")).not.toBeInTheDocument());
  });

  it("checks for new games and imports just those", async () => {
    const calls = serveSources();
    renderAt("/", [{ path: "/", element: <SavedAccounts /> }]);
    const user = userEvent.setup();
    expect(await screen.findByText("DrNykterstein")).toBeInTheDocument();
    expect(screen.getByText(/not checked yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check for new games" }));
    expect(await screen.findByTestId("check-result")).toHaveTextContent("2 new games");
    await user.click(screen.getByRole("button", { name: "Import 2 new games" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/imports/commit")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/imports/commit")[0].body).toEqual({
      source: "lichess",
      username: "DrNykterstein",
      external_ids: ["aaaaaaaa", "bbbbbbbb"],
    });
    expect(await screen.findByTestId("auto-analyzing")).toHaveTextContent("Analyzing 2 of them automatically");
  });

  it("says so when there is nothing new", async () => {
    serveSources({ new_games: [], already_saved: 20 });
    renderAt("/", [{ path: "/", element: <SavedAccounts /> }]);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Check for new games" }));
    expect(await screen.findByTestId("check-result")).toHaveTextContent("No new games among the latest 20");
  });

  it("forgets an account", async () => {
    const calls = serveSources();
    renderAt("/", [{ path: "/", element: <SavedAccounts /> }]);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Forget DrNykterstein on Lichess" }));
    await waitFor(() => expect(sent(calls, "DELETE", "/api/sources/s1")).toHaveLength(1));
  });
});
