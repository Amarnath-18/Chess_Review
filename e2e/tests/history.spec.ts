import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
const MOVES = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5";

const pgn = (white: string, black: string, date: string, result: string) =>
  `[Event "Casual"]\n[Date "${date}"]\n[White "${white}"]\n[Black "${black}"]\n[Result "${result}"]\n\n${MOVES} ${result}\n`;

const GAMES = [
  pgn("Zed", "Alice", "2024.01.10", "1-0"),
  pgn("Bruno", "Zed", "2024.03.20", "0-1"),
  pgn("Carla", "Dmitri", "2024.05.30", "1/2-1/2"),
];

/** Create the anonymous session and import games straight through the API. */
async function seed(page: Page, games: string[] = GAMES) {
  // Create the session BEFORE opening any page. If the app were loading at the same time it would
  // create its own session, the later cookie would replace the earlier, and the imports would be
  // split between two anonymous users.
  await page.request.post("/api/session", { headers: HEADERS });
  for (const text of games) {
    const r = await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: text } });
    expect(r.ok()).toBeTruthy();
  }
}

const count = (page: Page) => page.getByTestId("result-count");

test.describe("history", () => {
  test("search, filter, sort, share the URL and clear", async ({ page }, info) => {
    await seed(page);
    await page.goto("/games");
    await expect(count(page)).toHaveText("3 games");

    // search by player (either colour), after a short pause
    await page.getByLabel("Player").fill("zed");
    await expect(count(page)).toHaveText("2 games match");
    await expect(page).toHaveURL(/q=zed/);

    // combine with a result filter
    await page.getByLabel("Result").selectOption("0-1");
    await expect(count(page)).toHaveText("1 game match");
    await expect(page.getByRole("list").getByText("Bruno vs Zed")).toBeVisible();

    // the filtered view survives a reload and can be bookmarked
    await page.reload();
    await expect(count(page)).toHaveText("1 game match");
    await expect(page.getByLabel("Player")).toHaveValue("zed");
    await expect(page.getByLabel("Result")).toHaveValue("0-1");
    await page.screenshot({ path: `screenshots/09-history-filtered-${info.project.name}.png`, fullPage: true });

    // nothing matches: say so, and clearing brings everything back
    await page.getByLabel("Player").fill("nobody-at-all");
    await expect(page.getByText("No games match these filters.")).toBeVisible();
    await page.getByRole("button", { name: "Clear all filters" }).first().click();
    await expect(count(page)).toHaveText("3 games");
    await expect(page.getByLabel("Player")).toHaveValue("");
    await expect(page).not.toHaveURL(/q=/);
  });

  test("filter by date and by whether a game is analyzed", async ({ page }) => {
    await seed(page);
    await page.goto("/games");
    await page.getByLabel("Played from").fill("2024-02-01");
    await page.getByLabel("Played until").fill("2024-04-30");
    await expect(count(page)).toHaveText("1 game match");
    await page.getByRole("button", { name: "Clear all filters" }).first().click();

    await page.getByLabel("Analysis").selectOption("yes");
    await expect(page.getByText("No games match these filters.")).toBeVisible();
    await page.getByLabel("Analysis").selectOption("no");
    await expect(count(page)).toHaveText("3 games match");
  });

  test("order by date played or by when imported", async ({ page }) => {
    // imported newest-played first, so the two orders are exact opposites
    await seed(page, [
      pgn("Early", "X", "2025.06.01", "1-0"),
      pgn("Mid", "X", "2024.03.01", "1-0"),
      pgn("Late", "X", "2023.01.01", "1-0"),
    ]);
    await page.goto("/games");
    const titles = async () =>
      (await page.getByRole("list").getByRole("link").filter({ hasText: " vs " }).allInnerTexts()).map(
        (t) => t.split("\n")[0],
      );
    await expect.poll(titles).toEqual(["Early vs X", "Mid vs X", "Late vs X"]); // by date played
    await page.getByLabel("Sort by").selectOption("added");
    await expect.poll(titles).toEqual(["Late vs X", "Mid vs X", "Early vs X"]); // most recently imported first
    await page.reload(); // the choice is in the URL
    await expect(page.getByLabel("Sort by")).toHaveValue("added");
    await expect.poll(titles).toEqual(["Late vs X", "Mid vs X", "Early vs X"]);
  });

  test("download a single game and the filtered list as PGN files", async ({ page }) => {
    await seed(page);
    await page.goto("/games");

    const [one] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download PGN of Zed vs Alice" }).click(),
    ]);
    expect(one.suggestedFilename()).toBe("Zed-vs-Alice-2024-01-10.pgn");
    const single = fs.readFileSync((await one.path())!, "utf8");
    expect(single).toContain('[White "Zed"]');
    expect(single).not.toContain("Carla");

    await page.getByLabel("Player").fill("zed");
    await expect(count(page)).toHaveText("2 games match");
    const [all] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Export these as PGN" }).click(),
    ]);
    expect(all.suggestedFilename()).toMatch(/^chess-review-games-\d{4}-\d{2}-\d{2}\.pgn$/);
    const text = fs.readFileSync((await all.path())!, "utf8");
    expect((text.match(/\[Event /g) ?? []).length).toBe(2); // only the two matches, no Carla
    expect(text).toContain('[White "Bruno"]');
    expect(text).not.toContain("Carla");
  });

  test("an exported file can be imported again, unchanged", async ({ page, browser }) => {
    await seed(page);
    const exported = await (await page.request.get("/api/games/export")).text();

    const other = await browser.newContext();
    const p2 = await other.newPage();
    await p2.goto("/");
    await p2.getByLabel("Paste PGN").fill(exported);
    await p2.getByRole("button", { name: "Import PGN" }).click();
    await expect(p2.getByTestId("import-result")).toContainText("Imported 3 games");
    await other.close();
  });

  test("delete one game from the list", async ({ page }) => {
    await seed(page);
    await page.goto("/games");
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete Zed vs Alice" }).click();
    await expect(count(page)).toHaveText("2 games");
    await expect(page.getByText("Zed vs Alice")).toHaveCount(0);
  });

  test("paging through a longer history", async ({ page }) => {
    const many = Array.from({ length: 23 }, (_, i) =>
      pgn(`Player${String(i).padStart(2, "0")}`, "Opp", `2023.${String((i % 12) + 1).padStart(2, "0")}.15`, "1-0"),
    );
    await seed(page, many);
    await page.goto("/games");
    await expect(count(page)).toHaveText("23 games");
    await expect(page.getByTestId("page-info")).toHaveText("Page 1 of 2");
    await expect(page.getByRole("button", { name: /Previous/ })).toBeDisabled();
    await page.getByRole("button", { name: /Next/ }).click();
    await expect(page.getByTestId("page-info")).toHaveText("Page 2 of 2");
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByRole("list").getByRole("link").filter({ hasText: " vs " })).toHaveCount(3);
    await expect(page.getByRole("button", { name: /Next/ })).toBeDisabled();
  });
});

test.describe("settings and privacy", () => {
  test("saved defaults carry into the analysis form and the saved review", async ({ page }) => {
    await seed(page, [GAMES[0]]);
    await page.goto("/settings");
    await expect(page.getByLabel("Search depth")).toHaveValue("16");
    await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled();

    await page.getByLabel("Search depth").selectOption("10");
    await page.getByLabel("Engine lines").selectOption("2");
    await page.getByLabel(/Games per/).selectOption("50");
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();

    await page.reload(); // really stored on the server
    await expect(page.getByLabel("Search depth")).toHaveValue("10");
    await expect(page.getByLabel("Engine lines")).toHaveValue("2");

    await page.goto("/");
    await page.getByRole("tab", { name: "Lichess" }).click();
    await expect(page.getByLabel("Latest games")).toHaveValue("50");

    await page.goto("/games");
    await page.getByRole("link", { name: /^Zed vs Alice/ }).click();
    await expect(page.getByLabel("Search depth")).toHaveValue("10");
    await expect(page.getByLabel("Engine lines")).toHaveValue("2");
    await page.getByRole("button", { name: "Analyze game" }).click();
    await expect(page.getByText(/Stockfish .* depth 10 · 2 lines/)).toBeVisible({ timeout: 90_000 });
  });

  test("states how long data is kept and offers a download", async ({ page }, info) => {
    await seed(page);
    await page.goto("/settings");
    await expect(page.getByText(/If you don't visit for 30 days/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Download all 3 games (PGN)" })).toBeVisible();
    await page.screenshot({ path: `screenshots/10-settings-${info.project.name}.png`, fullPage: true });
  });

  test("delete all games keeps the session and settings", async ({ page }) => {
    await seed(page);
    await page.goto("/settings");
    await page.getByLabel("Search depth").selectOption("10");
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();

    page.once("dialog", (d) => d.dismiss()); // declining changes nothing
    await page.getByRole("button", { name: "Delete all my games" }).click();
    await expect(page.getByRole("link", { name: "Download all 3 games (PGN)" })).toBeVisible();

    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete all my games" }).click();
    await expect(page.getByText("Deleted 3 games.")).toBeVisible();
    await expect(page.getByText("No games to export yet.")).toBeVisible();

    await page.goto("/games");
    await expect(page.getByText(/haven't imported any games yet/)).toBeVisible();
    await page.goto("/settings");
    await expect(page.getByLabel("Search depth")).toHaveValue("10"); // still signed in, settings kept
  });

  test("delete everything wipes the data, the settings and the session", async ({ page }) => {
    await seed(page);
    await page.goto("/settings");
    await page.getByLabel("Engine lines").selectOption("1");
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();

    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete everything and start over" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto("/games");
    await expect(page.getByText(/haven't imported any games yet/)).toBeVisible();
    await page.goto("/settings");
    await expect(page.getByLabel("Engine lines")).toHaveValue("3"); // a fresh anonymous user
  });
});

test.describe("layout at this screen size", () => {
  for (const [name, path] of [
    ["history", "/games"],
    ["settings", "/settings"],
  ] as const) {
    test(`${name} fits the screen and has touch-sized controls`, async ({ page }) => {
      await seed(page);
      await page.goto(path);
      await page.getByRole("navigation", { name: "Main" }).waitFor();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);

      for (const link of await page.getByRole("navigation", { name: "Main" }).getByRole("link").all())
        expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      const controls =
        path === "/games"
          ? [page.getByRole("button", { name: "Delete Zed vs Alice" }), page.getByRole("link", { name: "Download PGN of Zed vs Alice" }), page.getByRole("link", { name: "Export all as PGN" })]
          : [page.getByRole("button", { name: "Delete all my games" }), page.getByRole("button", { name: "Delete everything and start over" })];
      for (const c of controls) expect((await c.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    });
  }
});
