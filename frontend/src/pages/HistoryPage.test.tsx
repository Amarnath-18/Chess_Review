import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GameSummary } from "../api/types";
import { makeGame } from "../test/fixtures";
import { type Call, mockApi, paramsOf, renderAt } from "../test/render";
import HistoryPage from "./HistoryPage";

afterEach(() => vi.unstubAllGlobals());

const row = (n: number, over: Partial<GameSummary> = {}): GameSummary => {
  const { moves: _m, pgn: _p, start_fen: _s, latest_job: _l, ...rest } = makeGame({
    id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
    white: `White${n}`,
    black: `Black${n}`,
    ...over,
  });
  return rest;
};

/** Serves /api/games like the server does: `total` games, the items for the requested page. */
function serve(total: number, items: (page: number) => GameSummary[]) {
  return mockApi((c) => {
    if (c.url.startsWith("/api/games?"))
      return {
        body: { items: items(Number(paramsOf(c).get("page") ?? 1)), total, page: 1, page_size: 20 },
      };
    if (c.method === "DELETE") return { status: 204, body: undefined };
  });
}

const lists = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/games?"));
const lastList = (calls: Call[]) => lists(calls).at(-1)!;
const open = (path = "/games") =>
  renderAt(path, [
    { path: "/games", element: <HistoryPage /> },
    { path: "/", element: <p>home</p> },
  ]);

describe("listing", () => {
  it("shows the games, how many there are, and links to each review and its PGN", async () => {
    serve(2, () => [row(1), row(2)]);
    open();
    expect(await screen.findByText("White1 vs Black1")).toBeInTheDocument();
    expect(screen.getByTestId("result-count")).toHaveTextContent("2 games");
    expect(screen.getByRole("link", { name: /^White1 vs Black1/ })).toHaveAttribute(
      "href",
      "/games/00000000-0000-0000-0000-000000000001",
    );
    expect(
      screen.getByRole("link", { name: "Download PGN of White1 vs Black1" }),
    ).toHaveAttribute("href", "/api/games/00000000-0000-0000-0000-000000000001/pgn");
  });

  it("asks for the first page of 20 with no filters", async () => {
    const calls = serve(1, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    const p = paramsOf(lastList(calls));
    expect([p.get("page"), p.get("page_size")]).toEqual(["1", "20"]);
    for (const k of ["q", "source", "result", "analyzed", "date_from", "date_to", "sort"])
      expect(p.has(k)).toBe(false);
  });

  it("says so when there are no games at all", async () => {
    serve(0, () => []);
    open();
    expect(await screen.findByText(/haven't imported any games yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import your first game" })).toHaveAttribute("href", "/");
    expect(screen.queryByText(/Export/)).toBeNull();
  });

  it("shows an error when the list cannot be loaded", async () => {
    mockApi((c) =>
      c.url.startsWith("/api/games?") ? { status: 500, body: { detail: "Internal Server Error" } } : undefined,
    );
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your games");
  });
});

describe("filters", () => {
  it("searches by player after a short pause, not on every keystroke", async () => {
    const calls = serve(1, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    const before = lists(calls).length;
    await userEvent.setup().type(screen.getByLabelText("Player"), "alice");
    expect(lists(calls).length).toBe(before); // nothing is sent while typing
    await waitFor(() => expect(paramsOf(lastList(calls)).get("q")).toBe("alice"));
    expect(lists(calls).length - before).toBe(1); // one request for the whole word
  });

  it.each([
    ["Source", "lichess", "source", "lichess"],
    ["Result", "1-0", "result", "1-0"],
    ["Analysis", "yes", "analyzed", "true"],
    ["Analysis", "no", "analyzed", "false"],
    ["Sort by", "added", "sort", "added"],
  ])("%s = %s is sent to the server", async (label, value, param, expected) => {
    const calls = serve(1, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    await userEvent.setup().selectOptions(screen.getByLabelText(label), value);
    await waitFor(() => expect(paramsOf(lastList(calls)).get(param)).toBe(expected));
  });

  it("sends the date range", async () => {
    const calls = serve(1, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Played from"), "2024-01-05");
    await user.type(screen.getByLabelText("Played until"), "2024-02-10");
    await waitFor(() => {
      const p = paramsOf(lastList(calls));
      expect([p.get("date_from"), p.get("date_to")]).toEqual(["2024-01-05", "2024-02-10"]);
    });
  });

  it("starts from the filters in the URL and shows them in the controls", async () => {
    const calls = serve(1, () => [row(1)]);
    open("/games?q=bob&source=chesscom&result=0-1&analyzed=yes&sort=added&page=2");
    await screen.findByText("White1 vs Black1");
    expect(Object.fromEntries(paramsOf(lastList(calls)))).toMatchObject({
      q: "bob",
      source: "chesscom",
      result: "0-1",
      analyzed: "true",
      sort: "added",
      page: "2",
    });
    expect(screen.getByLabelText("Player")).toHaveValue("bob");
    expect(screen.getByLabelText("Source")).toHaveValue("chesscom");
    expect(screen.getByLabelText("Result")).toHaveValue("0-1");
    expect(screen.getByLabelText("Analysis")).toHaveValue("yes");
    expect(screen.getByLabelText("Sort by")).toHaveValue("added");
  });

  it("goes back to page 1 when a filter changes", async () => {
    const calls = serve(45, () => [row(1)]);
    open("/games?page=3");
    await screen.findByText("White1 vs Black1");
    await userEvent.setup().selectOptions(screen.getByLabelText("Source"), "pgn");
    await waitFor(() => {
      const p = paramsOf(lastList(calls));
      expect([p.get("source"), p.get("page")]).toEqual(["pgn", "1"]);
    });
  });

  it("explains an empty result and clears the filters", async () => {
    const calls = mockApi((c) => {
      if (!c.url.startsWith("/api/games?")) return undefined;
      const filtered = !!paramsOf(c).get("q");
      return {
        body: { items: filtered ? [] : [row(1)], total: filtered ? 0 : 1, page: 1, page_size: 20 },
      };
    });
    open("/games?q=nobody");
    expect(await screen.findByText("No games match these filters.")).toBeInTheDocument();
    expect(screen.queryByText(/Export/)).toBeNull();

    await userEvent.setup().click(screen.getAllByRole("button", { name: "Clear all filters" })[0]);
    expect(await screen.findByText("White1 vs Black1")).toBeInTheDocument();
    expect(paramsOf(lastList(calls)).has("q")).toBe(false);
    expect(screen.getByLabelText("Player")).toHaveValue("");
  });

  it("only offers 'clear' when something is filtered", async () => {
    serve(1, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    expect(screen.queryByRole("button", { name: "Clear all filters" })).toBeNull();
  });

  it("says how many games match when filtered", async () => {
    serve(3, () => [row(1), row(2), row(3)]);
    open("/games?result=1-0");
    expect(await screen.findByText("3 games match")).toBeInTheDocument();
  });
});

describe("pages", () => {
  const many = (page: number) => [row(page * 100)];

  it("shows the page number and moves between pages", async () => {
    const calls = serve(45, many);
    open();
    await screen.findByText("White100 vs Black100");
    expect(screen.getByTestId("page-info")).toHaveTextContent("Page 1 of 3");
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("White200 vs Black200")).toBeInTheDocument();
    expect(paramsOf(lastList(calls)).get("page")).toBe("2");
    expect(screen.getByTestId("page-info")).toHaveTextContent("Page 2 of 3");

    await user.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("White300 vs Black300")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();
  });

  it("hides the pager when everything fits on one page", async () => {
    serve(20, () => [row(1)]);
    open();
    await screen.findByText("White1 vs Black1");
    expect(screen.queryByRole("navigation", { name: "Pages" })).toBeNull();
  });

  it("steps back a page when the last game on a later page is gone", async () => {
    const calls = mockApi((c) => {
      if (!c.url.startsWith("/api/games?")) return undefined;
      const page = Number(paramsOf(c).get("page"));
      return { body: { items: page === 1 ? [row(1)] : [], total: 20, page, page_size: 20 } };
    });
    open("/games?page=2");
    expect(await screen.findByText("White1 vs Black1")).toBeInTheDocument();
    expect(paramsOf(lastList(calls)).get("page")).toBe("1");
  });
});

describe("export", () => {
  it("exports everything when nothing is filtered", async () => {
    serve(2, () => [row(1), row(2)]);
    open();
    const link = await screen.findByRole("link", { name: "Export all as PGN" });
    expect(link).toHaveAttribute("href", "/api/games/export");
    expect(link).toHaveAttribute("download");
  });

  it("exports exactly what the filters show", async () => {
    serve(2, () => [row(1), row(2)]);
    open("/games?q=bob&result=1-0&analyzed=no&source=lichess&sort=added&page=2");
    const link = await screen.findByRole("link", { name: "Export these as PGN" });
    const url = new URL(link.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe("/api/games/export");
    // no page: the file holds every match, not just the visible page
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: "bob",
      result: "1-0",
      analyzed: "false",
      source: "lichess",
      sort: "added",
    });
  });
});

describe("deleting", () => {
  it("asks first, and does nothing if you decline", async () => {
    const calls = serve(1, () => [row(1)]);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    open();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Delete White1 vs Black1" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be undone"));
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
  });

  it("deletes the game and refreshes the list", async () => {
    const calls = serve(1, () => [row(1)]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Delete White1 vs Black1" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1));
    expect(calls.find((c) => c.method === "DELETE")!.url).toBe(
      "/api/games/00000000-0000-0000-0000-000000000001",
    );
  });
});

it("keeps the old rows on screen while the next page loads", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const ok = (body: unknown) =>
    ({ ok: true, status: 200, statusText: "OK", json: async () => body }) as Response;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/session") return ok({});
      const page = Number(new URL(url, "http://x").searchParams.get("page"));
      if (page === 2) await gate;
      return ok({ items: [row(page)], total: 45, page, page_size: 20 });
    }),
  );
  open();
  await screen.findByText("White1 vs Black1");
  await userEvent.setup().click(screen.getByRole("button", { name: /Next/ }));
  expect(within(screen.getByRole("list")).getByText("White1 vs Black1")).toBeVisible(); // not blanked
  release();
  expect(await screen.findByText("White2 vs Black2")).toBeInTheDocument();
});
