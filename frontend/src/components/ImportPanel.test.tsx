import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GameSummary, PreviewGame } from "../api/types";
import { makeGame } from "../test/fixtures";
import { type Call, mockApi } from "../test/render";
import { ImportPanel, usernameProblem } from "./ImportPanel";

afterEach(() => vi.unstubAllGlobals());

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<ImportPanel />} />
          <Route path="/games/:id" element={<div data-testid="review-page" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const pg = (id: string, over: Partial<PreviewGame> = {}): PreviewGame => ({
  external_id: id,
  url: `https://www.chess.com/game/live/${id}`,
  white: `White${id}`,
  black: `Black${id}`,
  white_elo: 1500,
  black_elo: 1480,
  result: "1-0",
  played_at: "2026-09-08",
  time_control: "300",
  opening_name: "Italian Game",
  ply_count: 40,
  already_imported: false,
  importable: true,
  problem: null,
  ...over,
});

const summary = (id: string, external: string, source = "chesscom"): GameSummary => {
  const { moves: _m, pgn: _p, start_fen: _s, latest_job: _l, ...rest } = makeGame({ id, source, external_id: external });
  return rest;
};

const preview = (games: PreviewGame[], extra = {}) => ({
  source: "chesscom",
  username: "hikaru",
  games,
  skipped_archives: 0,
  note: null,
  ...extra,
});

const calls = (c: Call[], url: string) => c.filter((x) => x.url === url);

async function openTab(name: string) {
  await userEvent.setup().click(screen.getByRole("tab", { name }));
}

async function search(user: ReturnType<typeof userEvent.setup>, name = "hikaru") {
  await user.type(screen.getByLabelText(/username/i), name);
  await user.click(screen.getByRole("button", { name: "Find games" }));
}

describe("tabs", () => {
  it("offers PGN, Chess.com, Lichess and game link", async () => {
    mockApi(() => undefined);
    renderPanel();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["PGN", "Chess.com", "Lichess", "Game link"]);
    expect(screen.getByLabelText("Paste PGN")).toBeInTheDocument();

    await openTab("Chess.com");
    expect(screen.getByLabelText("Chess.com username")).toBeInTheDocument();
    await openTab("Lichess");
    expect(screen.getByLabelText("Lichess username")).toBeInTheDocument();
    await openTab("Game link");
    expect(screen.getByLabelText("Chess.com or Lichess game link")).toBeInTheDocument();
  });
});

describe("username rules", () => {
  it("mirrors the server's rules for each site", () => {
    expect(usernameProblem("chesscom", "")).toBeNull();
    expect(usernameProblem("chesscom", "hikaru")).toBeNull();
    expect(usernameProblem("chesscom", "ab")).toMatch(/3-25/);
    expect(usernameProblem("lichess", "ab")).toBeNull();
    expect(usernameProblem("lichess", "x")).toMatch(/2-30/);
    expect(usernameProblem("chesscom", "has space")).toMatch(/letters, numbers/);
    expect(usernameProblem("lichess", "../etc")).toMatch(/letters, numbers/);
  });

  it("explains a bad username and does not send a request", async () => {
    const calls = mockApi(() => undefined);
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Chess.com username"), "a b");
    expect(screen.getByText(/letters, numbers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find games" })).toBeDisabled();
    expect(calls.filter((c) => c.url.includes("/imports/"))).toEqual([]);
  });

  it("keeps the search button disabled until something is typed", async () => {
    mockApi(() => undefined);
    renderPanel();
    await openTab("Lichess");
    expect(screen.getByRole("button", { name: "Find games" })).toBeDisabled();
  });
});

describe("finding games", () => {
  const games = [
    pg("1"),
    pg("2", { already_imported: true }),
    pg("3", { importable: false, problem: "chess960 games are not supported (standard chess only)" }),
  ];

  it("sends the username and count, and lists what was found", async () => {
    const c = mockApi((call) =>
      call.url === "/api/imports/preview" ? { body: preview(games, { note: "1 month of the archive could not be loaded, so some games may be missing." }) } : undefined,
    );
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Latest games"), "50");
    await search(user);

    await screen.findByTestId("found-games");
    expect(calls(c, "/api/imports/preview")[0].body).toEqual({ source: "chesscom", username: "hikaru", max_games: 50 });
    expect(screen.getByText("White1 (1500) vs Black1 (1480)")).toBeInTheDocument();
    expect(screen.getAllByText(/Italian Game/)).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("could not be loaded");
  });

  it("pre-selects only new, importable games and explains the others", async () => {
    mockApi((call) => (call.url === "/api/imports/preview" ? { body: preview(games) } : undefined));
    renderPanel();
    await openTab("Chess.com");
    await search(userEvent.setup());
    await screen.findByTestId("found-games");

    expect(screen.getByTestId("pick-1")).toBeChecked();
    expect(screen.getByTestId("pick-2")).toBeDisabled();
    expect(screen.getByTestId("pick-2")).not.toBeChecked();
    expect(screen.getByText("Already imported")).toBeInTheDocument();
    expect(screen.getByTestId("pick-3")).toBeDisabled();
    expect(screen.getByText(/Can't import: chess960/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 1 selected game" })).toBeEnabled();
  });

  it("lets the user change the selection", async () => {
    const many = [pg("1"), pg("2", { white: "W2" }), pg("3", { white: "W3" })];
    mockApi((call) => (call.url === "/api/imports/preview" ? { body: preview(many) } : undefined));
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await search(user);
    await screen.findByTestId("found-games");
    expect(screen.getByRole("button", { name: "Import 3 selected games" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: /^Import 0 selected/ })).toBeDisabled();
    await user.click(screen.getByTestId("pick-2"));
    expect(screen.getByRole("button", { name: "Import 1 selected game" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Select all new" }));
    expect(screen.getByRole("button", { name: "Import 3 selected games" })).toBeInTheDocument();
  });

  it("says so when there are no games", async () => {
    mockApi((call) => (call.url === "/api/imports/preview" ? { body: preview([]) } : undefined));
    renderPanel();
    await openTab("Lichess");
    await search(userEvent.setup(), "someone");
    expect(await screen.findByText(/No games found for hikaru/)).toBeInTheDocument();
  });

  it.each([
    [404, 'Chess.com user "nobody" was not found.'],
    [429, "Chess.com is rate limiting requests. Please wait about a minute and try again."],
    [502, "Chess.com did not respond in time. Please try again."],
  ])("shows the server's message for a %i", async (status, detail) => {
    mockApi((call) => (call.url === "/api/imports/preview" ? { status, body: { detail } } : undefined));
    renderPanel();
    await openTab("Chess.com");
    await search(userEvent.setup(), "nobody");
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.queryByTestId("found-games")).toBeNull();
  });
});

describe("importing the picked games", () => {
  it("sends only the selected ids, then marks them imported", async () => {
    const many = [pg("1"), pg("2", { white: "W2" }), pg("3", { white: "W3" })];
    const c = mockApi((call) => {
      if (call.url === "/api/imports/preview") return { body: preview(many) };
      if (call.url === "/api/imports/commit")
        return {
          body: {
            imported: [summary("a1", "1"), summary("a3", "3")],
            duplicates: [],
            errors: [],
          },
        };
    });
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await search(user);
    await screen.findByTestId("found-games");
    await user.click(screen.getByTestId("pick-2")); // untick game 2

    await user.click(screen.getByRole("button", { name: "Import 2 selected games" }));
    const result = await screen.findByTestId("import-result");
    expect(calls(c, "/api/imports/commit")[0].body).toEqual({
      source: "chesscom",
      username: "hikaru",
      external_ids: ["1", "3"],
    });
    expect(within(result).getByText("Imported 2 games:")).toBeInTheDocument();
    expect(within(result).getAllByRole("link")).toHaveLength(2);

    // the imported rows are now shown as such and cannot be picked again
    expect(screen.getByTestId("pick-1")).toBeDisabled();
    expect(screen.getByTestId("pick-3")).toBeDisabled();
    expect(screen.getByTestId("pick-2")).toBeEnabled();
    expect(screen.getAllByText("Already imported")).toHaveLength(2);
  });

  it("reports games that could not be imported next to those that were", async () => {
    mockApi((call) => {
      if (call.url === "/api/imports/preview") return { body: preview([pg("1"), pg("2", { white: "W2" })]) };
      if (call.url === "/api/imports/commit")
        return {
          body: {
            imported: [summary("a1", "1")],
            duplicates: [],
            errors: [{ index: 2, message: "Game 2 is no longer among the latest games. Search again." }],
          },
        };
    });
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await search(user);
    await screen.findByTestId("found-games");
    await user.click(screen.getByRole("button", { name: "Import 2 selected games" }));
    const result = await screen.findByTestId("import-result");
    expect(result).toHaveTextContent("Imported 1 game:");
    expect(within(result).getByRole("alert")).toHaveTextContent("no longer among the latest games");
    expect(screen.getByTestId("pick-1")).toBeDisabled(); // imported
    expect(screen.getByTestId("pick-2")).toBeEnabled(); // failed, can try again
  });

  it("works for Lichess too", async () => {
    const c = mockApi((call) => {
      if (call.url === "/api/imports/preview")
        return { body: preview([pg("abcd1234", { url: "https://lichess.org/abcd1234" })], { source: "lichess", username: "DrNykterstein" }) };
      if (call.url === "/api/imports/commit")
        return { body: { imported: [summary("l1", "abcd1234", "lichess")], duplicates: [], errors: [] } };
    });
    renderPanel();
    await openTab("Lichess");
    const user = userEvent.setup();
    await search(user, "DrNykterstein");
    await screen.findByTestId("found-games");
    await user.click(screen.getByRole("button", { name: "Import 1 selected game" }));
    await screen.findByTestId("import-result");
    expect(calls(c, "/api/imports/commit")[0].body).toEqual({
      source: "lichess",
      username: "DrNykterstein",
      external_ids: ["abcd1234"],
    });
  });
});

describe("importing from a link", () => {
  it("needs no username for Lichess and opens the game", async () => {
    const c = mockApi((call) =>
      call.url === "/api/imports/url"
        ? { body: { imported: [summary("g9", "abcd1234", "lichess")], duplicates: [], errors: [] } }
        : undefined,
    );
    renderPanel();
    await openTab("Game link");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Chess.com or Lichess game link"), "https://lichess.org/abcd1234");
    expect(screen.queryByLabelText(/username of one of the players/i)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Import game" }));
    await screen.findByTestId("review-page");
    expect(calls(c, "/api/imports/url")[0].body).toEqual({ url: "https://lichess.org/abcd1234", username_hint: null });
  });

  it("asks for a username for Chess.com links and sends it along", async () => {
    const c = mockApi((call) =>
      call.url === "/api/imports/url"
        ? { body: { imported: [summary("g9", "183193101523")], duplicates: [], errors: [] } }
        : undefined,
    );
    renderPanel();
    await openTab("Game link");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Chess.com or Lichess game link"), "https://www.chess.com/game/live/183193101523");
    const submit = screen.getByRole("button", { name: "Import game" });
    expect(screen.getByLabelText(/username of one of the players/i)).toBeInTheDocument();
    expect(screen.getByText(/can't look a game up from its link alone/i)).toBeInTheDocument();
    expect(submit).toBeDisabled(); // a username is required first

    await user.type(screen.getByLabelText(/username of one of the players/i), "hikaru");
    expect(submit).toBeEnabled();
    await user.click(submit);
    await screen.findByTestId("review-page");
    expect(calls(c, "/api/imports/url")[0].body).toEqual({
      url: "https://www.chess.com/game/live/183193101523",
      username_hint: "hikaru",
    });
  });

  it("shows why a link could not be imported", async () => {
    mockApi((call) =>
      call.url === "/api/imports/url"
        ? { status: 404, body: { detail: "Lichess game zzzzzzzz was not found (or it is private)." } }
        : undefined,
    );
    renderPanel();
    await openTab("Game link");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Chess.com or Lichess game link"), "https://lichess.org/zzzzzzzz");
    await user.click(screen.getByRole("button", { name: "Import game" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("was not found");
    expect(screen.queryByTestId("review-page")).toBeNull();
  });

  it("stays on the page and lists the problem when the game itself cannot be read", async () => {
    mockApi((call) =>
      call.url === "/api/imports/url"
        ? {
            status: 422,
            body: {
              imported: [],
              duplicates: [],
              errors: [{ index: 1, message: "Game 183193101523: chess960 games are not supported (standard chess only)" }],
              detail: "x",
            },
          }
        : undefined,
    );
    renderPanel();
    await openTab("Game link");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Chess.com or Lichess game link"), "https://lichess.org/abcd1234");
    await user.click(screen.getByRole("button", { name: "Import game" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("chess960");
  });
});

describe("pasting a PGN still works", () => {
  it("opens the game after a single successful import", async () => {
    const c = mockApi((call) =>
      call.url === "/api/imports/pgn"
        ? { body: { imported: [summary("p1", "")], duplicates: [], errors: [] } }
        : undefined,
    );
    renderPanel();
    await userEvent.setup().type(screen.getByLabelText("Paste PGN"), "1. e4 e5");
    await userEvent.setup().click(screen.getByRole("button", { name: "Import PGN" }));
    await screen.findByTestId("review-page");
    await waitFor(() => expect(calls(c, "/api/imports/pgn")[0].body).toEqual({ pgn_text: "1. e4 e5" }));
  });
});

describe("saved import preference", () => {
  it("sets how many games a search fetches, and can still be changed", async () => {
    const c = mockApi((call) => {
      if (call.url === "/api/settings")
        return { body: { default_depth: 16, default_multipv: 3, import_count: 50, max_depth: 22, max_multipv: 5, retention_days: 30 } };
      if (call.url === "/api/imports/preview") return { body: preview([pg("1")]) };
    });
    renderPanel();
    await openTab("Chess.com");
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByLabelText("Latest games")).toHaveValue("50"));
    await search(user);
    await screen.findByTestId("found-games");
    expect(calls(c, "/api/imports/preview")[0].body).toMatchObject({ max_games: 50 });
  });
});
