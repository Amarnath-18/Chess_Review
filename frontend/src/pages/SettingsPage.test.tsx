import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Settings } from "../api/types";
import { type Call, mockApi, renderAt } from "../test/render";
import SettingsPage from "./SettingsPage";

afterEach(() => vi.unstubAllGlobals());

const base: Settings = {
  default_depth: 16,
  default_multipv: 3,
  import_count: 20,
  max_depth: 22,
  max_multipv: 5,
  retention_days: 30,
};

function serve(settings: Partial<Settings> = {}, gameCount = 3) {
  let current = { ...base, ...settings };
  return mockApi((c) => {
    if (c.url === "/api/settings" && c.method === "GET") return { body: current };
    if (c.url === "/api/settings" && c.method === "PUT") {
      current = { ...current, ...(c.body as object) };
      return { body: current };
    }
    if (c.url.startsWith("/api/games?"))
      return { body: { items: [], total: gameCount, page: 1, page_size: 1 } };
    if (c.url === "/api/me/games" && c.method === "DELETE")
      return { body: { deleted: gameCount } };
    if (c.url === "/api/me" && c.method === "DELETE") return { status: 204, body: undefined };
  });
}

const open = () =>
  renderAt("/settings", [
    { path: "/settings", element: <SettingsPage /> },
    { path: "/", element: <p data-testid="home">home</p> },
  ]);
const sent = (calls: Call[], method: string, url: string) =>
  calls.filter((c) => c.method === method && c.url === url);

describe("preferences", () => {
  it("shows the saved values", async () => {
    serve({ default_depth: 18, default_multipv: 2, import_count: 50 });
    open();
    expect(await screen.findByLabelText("Search depth")).toHaveValue("18");
    expect(screen.getByLabelText("Engine lines")).toHaveValue("2");
    expect(screen.getByLabelText(/Games per/)).toHaveValue("50");
  });

  it("only enables Save once something changed, then saves exactly that", async () => {
    const calls = serve();
    open();
    const save = await screen.findByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Search depth"), "20");
    await user.selectOptions(screen.getByLabelText("Engine lines"), "4");
    expect(save).toBeEnabled();
    await user.click(save);

    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
    expect(sent(calls, "PUT", "/api/settings")[0].body).toEqual({
      default_depth: 20,
      default_multipv: 4,
      import_count: 20,
    });
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled(); // nothing pending now
  });

  it("only offers choices the server allows", async () => {
    serve({ max_depth: 14, max_multipv: 3 });
    open();
    const depths = within(await screen.findByLabelText("Search depth")).getAllByRole("option");
    expect(depths.map((o) => o.getAttribute("value"))).toEqual(["10", "14", "16"]); // 16 is the saved value
    const lines = within(screen.getByLabelText("Engine lines")).getAllByRole("option");
    expect(lines.map((o) => o.getAttribute("value"))).toEqual(["1", "2", "3"]);
  });

  it("includes an unusual saved depth so it can be displayed", async () => {
    serve({ default_depth: 13 });
    open();
    const select = await screen.findByLabelText("Search depth");
    expect(select).toHaveValue("13");
    expect(within(select).getByRole("option", { name: "Depth 13" })).toBeInTheDocument();
  });

  it("shows the server's message when saving is refused", async () => {
    mockApi((c) => {
      if (c.url === "/api/settings" && c.method === "GET") return { body: base };
      if (c.url === "/api/settings" && c.method === "PUT")
        return { status: 422, body: { detail: "Depth must be between 1 and 22." } };
      if (c.url.startsWith("/api/games?")) return { body: { items: [], total: 0, page: 1, page_size: 1 } };
    });
    open();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Search depth"), "10");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Depth must be between 1 and 22.");
  });

  it("shows an error if the settings cannot be loaded", async () => {
    mockApi((c) => {
      if (c.url === "/api/settings") return { status: 500, body: { detail: "boom" } };
      if (c.url.startsWith("/api/games?")) return { body: { items: [], total: 0, page: 1, page_size: 1 } };
    });
    open();
    // the query retries once before giving up, so allow for that delay
    expect(
      await screen.findByText(/Could not load your settings/, {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  });
});

describe("privacy", () => {
  it("states how long data is kept", async () => {
    serve({ retention_days: 45 });
    open();
    expect(await screen.findByText(/If you don't visit for 45 days/)).toBeInTheDocument();
  });

  it("says data is kept until deleted when automatic deletion is off", async () => {
    serve({ retention_days: 0 });
    open();
    expect(await screen.findByText(/kept until you delete it/)).toBeInTheDocument();
  });

  it("offers a download of everything when there are games", async () => {
    serve({}, 3);
    open();
    const link = await screen.findByRole("link", { name: "Download all 3 games (PGN)" });
    expect(link).toHaveAttribute("href", "/api/games/export");
    expect(link).toHaveAttribute("download");
  });

  it("does not offer a download when there is nothing to export", async () => {
    serve({}, 0);
    open();
    expect(await screen.findByText("No games to export yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download all/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Delete all my games" })).toBeDisabled();
  });

  it("deletes all games only after confirmation", async () => {
    const calls = serve({}, 3);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    open();
    const button = await screen.findByRole("button", { name: "Delete all my games" });
    await waitFor(() => expect(button).toBeEnabled());
    const user = userEvent.setup();

    await user.click(button);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be undone"));
    expect(sent(calls, "DELETE", "/api/me/games")).toHaveLength(0);

    confirm.mockReturnValue(true);
    await user.click(button);
    expect(await screen.findByText("Deleted 3 games.")).toBeInTheDocument();
    expect(sent(calls, "DELETE", "/api/me/games")).toHaveLength(1);
  });

  it("'delete everything' asks first, then returns to the start page", async () => {
    const calls = serve();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    open();
    const button = await screen.findByRole("button", { name: "Delete everything and start over" });
    const user = userEvent.setup();

    await user.click(button);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("sign this browser out"));
    expect(sent(calls, "DELETE", "/api/me")).toHaveLength(0);

    confirm.mockReturnValue(true);
    await user.click(button);
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(sent(calls, "DELETE", "/api/me")).toHaveLength(1);
  });

  it("shows the server's message if deleting fails", async () => {
    mockApi((c) => {
      if (c.url === "/api/settings") return { body: base };
      if (c.url.startsWith("/api/games?")) return { body: { items: [], total: 2, page: 1, page_size: 1 } };
      if (c.url === "/api/me/games") return { status: 500, body: { detail: "Could not delete right now." } };
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open();
    const button = await screen.findByRole("button", { name: "Delete all my games" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.setup().click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete right now.");
  });
});
