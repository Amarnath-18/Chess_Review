import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
const PGN = `[Event "Italian, short"]
[White "Alice"]
[Black "Bob"]
[TimeControl "300+3"]
[Result "*"]

1. e4 {[%clk 0:05:02]} e5 {[%clk 0:05:01]} 2. Nf3 {[%clk 0:04:58]} Nc6 {[%clk 0:04:50]}
3. Bc4 {[%clk 0:04:55]} Bc5 {[%clk 0:04:40]} 4. c3 {[%clk 0:04:50]} Nf6 {[%clk 0:00:20]}
5. d4 {[%clk 0:04:40]} exd4 {[%clk 0:00:15]} 6. cxd4 {[%clk 0:04:30]} Bb4+ {[%clk 0:00:10]}
7. Nc3 {[%clk 0:04:20]} Nxe4 {[%clk 0:00:08]} 8. O-O {[%clk 0:04:10]} *
`;

async function seed(page: Page): Promise<string> {
  await page.request.post("/api/session", { headers: HEADERS });
  const r = await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: PGN } });
  return (await r.json()).imported[0].id as string;
}

/** WCAG 2.1 A + AA, with a readable list of what failed. */
async function audit(page: Page, what: string) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const report = violations
    .map(
      (v) =>
        `[${v.impact}] ${v.id}: ${v.help}\n` +
        v.nodes.slice(0, 4).map((n) => `    ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1] ?? ""}`).join("\n"),
    )
    .join("\n");
  expect(violations, `${what} has accessibility problems:\n${report}`).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibility (${scheme} theme)`, () => {
    test.use({ colorScheme: scheme });

    test("import page, every tab", async ({ page }) => {
      await seed(page);
      // a remembered account adds the "Your accounts" card to the page
      await page.request.post("/api/sources", { headers: HEADERS, data: { source: "lichess", username: "DrNykterstein" } });
      await page.goto("/");
      await expect(page.getByLabel("Paste PGN")).toBeVisible();
      await audit(page, "PGN tab");
      for (const tab of ["Chess.com", "Lichess", "Game link"]) {
        await page.getByRole("tab", { name: tab }).click();
        await audit(page, `${tab} tab`);
      }
    });

    test("train and statistics pages", async ({ page }) => {
      await seed(page);
      await page.request.put("/api/settings", { headers: HEADERS, data: { my_names: ["Alice"] } });
      for (const [path, heading] of [["/train", "Train"], ["/stats", "Your statistics"]]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
        await audit(page, `${heading} page`);
      }
    });

    test("games and settings pages", async ({ page }) => {
      await seed(page);
      await page.goto("/games");
      await expect(page.getByTestId("result-count")).toHaveText("1 game");
      await audit(page, "games page");
      await page.getByLabel("Player").fill("zzz");
      await expect(page.getByText("No games match these filters.")).toBeVisible();
      await audit(page, "games page with no matches");
      await page.goto("/settings");
      await expect(page.getByLabel("Search depth")).toBeVisible();
      await audit(page, "settings page");
    });

    test("review page: not analyzed, analyzed, exploring a variation", async ({ page }, info) => {
      const mobile = info.project.name === "mobile";
      const id = await seed(page);
      await page.goto(`/games/${id}`);
      await expect(page.getByTestId("board")).toBeVisible();
      await audit(page, "review page before analysis");

      await page.getByLabel("Search depth").selectOption("10");
      await page.getByRole("button", { name: "Analyze game" }).click();
      await expect(page.getByText(/Stockfish .* depth 10/)).toBeVisible({ timeout: 90_000 });
      await page.getByRole("button", { name: "Next move" }).click();
      await page.getByRole("button", { name: "Next move" }).click();
      if (mobile) {
        // on a phone the panels are tabs: audit each one
        for (const tab of ["Moves", "Graph", "Engine", "Summary", "Time", "Notes"]) {
          await page.getByRole("tab", { name: tab }).click();
          await audit(page, `review page, ${tab} tab`);
        }
        await page.getByRole("tab", { name: "Engine" }).click();
      } else {
        await audit(page, "review page, analyzed");
      }

      // start a variation by playing an engine line (works with mouse, keyboard and touch)
      await page.getByRole("group", { name: /^Line 1/ }).getByRole("button").first().click();
      await expect(page.getByTestId("variation-banner")).toBeVisible();
      await audit(page, "review page, exploring a variation");
    });
  });
}

test.describe("keyboard and screen readers", () => {
  test("pages have distinct titles and landmarks", async ({ page }) => {
    const id = await seed(page);
    const titles: Record<string, string> = {};
    for (const [path, name] of [["/", "import"], ["/games", "games"], ["/settings", "settings"], [`/games/${id}`, "review"]]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("banner")).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      titles[name] = await page.title();
    }
    expect(new Set(Object.values(titles)).size).toBe(4); // each page has its own title
    for (const t of Object.values(titles)) expect(t).toContain("Chess Review Lab");
  });

  test("a keyboard user can skip the navigation", async ({ page }) => {
    await seed(page);
    await page.goto("/games");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });

  test("everything on the review page can be reached and used with the keyboard", async ({ page }) => {
    const id = await seed(page);
    await page.goto(`/games/${id}`);
    await expect(page.getByTestId("board")).toBeVisible();
    // the move controls are real buttons, reachable by Tab, activated by Enter / Space
    await page.getByRole("button", { name: "Next move" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("current-move")).toContainText("1. e4");
    await page.keyboard.press("Space");
    await expect(page.getByTestId("current-move")).toContainText("1... e5");
    // shortcuts work while focus is on a button, too
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("current-move")).toContainText("2. Nf3");
    // a visible focus ring on the focused control
    const outline = await page.getByRole("button", { name: "Next move" }).evaluate(
      (el) => getComputedStyle(el).outlineStyle,
    );
    expect(outline).not.toBe("none");
  });

  test("the page and the board respect 'reduce motion'", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce" });
    const page = await ctx.newPage();
    const id = await seed(page);
    await page.goto(`/games/${id}`);
    await expect(page.getByTestId("board")).toBeVisible();
    const duration = await page.getByRole("button", { name: "Next move" }).evaluate(
      (el) => getComputedStyle(el).transitionDuration,
    );
    expect(parseFloat(duration)).toBeLessThan(0.01);
    await ctx.close();
  });
});
