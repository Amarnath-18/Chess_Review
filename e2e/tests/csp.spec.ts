import { expect, test } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
const PGN = `[White "Alice"]\n[Black "Bob"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 *\n`;

/**
 * The production web server sends a strict Content-Security-Policy. This walks the main flows and
 * fails on any browser console error, in particular a blocked script, style, image or request.
 * (On the dev server there is no policy, so it simply checks for console errors.)
 */
test("no console errors or policy violations through the main flows", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`uncaught: ${e.message}`));
  page.on("requestfailed", (r) => {
    // a request still in flight when we move to the next page is cancelled by the browser: not a fault
    if (r.failure()?.errorText !== "net::ERR_ABORTED")
      problems.push(`request failed: ${r.url()} (${r.failure()?.errorText})`);
  });

  await page.request.post("/api/session", { headers: HEADERS });
  await page.goto("/");
  for (const tab of ["Chess.com", "Lichess", "Game link", "PGN"])
    await page.getByRole("tab", { name: tab }).click();

  await page.getByLabel("Paste PGN").fill(PGN);
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByRole("heading", { name: "Alice vs Bob" })).toBeVisible();

  await page.getByLabel("Search depth").selectOption("10");
  await page.getByRole("button", { name: "Analyze game" }).click();
  await expect(page.getByText(/Stockfish .* depth 10/)).toBeVisible({ timeout: 90_000 });

  // board, graph, engine lines, a variation, flipping, all of which draw SVG and inline styles
  await page.getByRole("button", { name: "Next move" }).click();
  await page.getByRole("button", { name: "Next move" }).click();
  await expect(page.getByTestId("move-mark")).toBeVisible();
  const mobile = test.info().project.name === "mobile";
  if (mobile) await page.getByRole("tab", { name: "Graph" }).click(); // phones show the panels as tabs
  await page.getByTestId("eval-graph").click({ position: { x: 100, y: 40 } });
  await page.getByRole("button", { name: "Flip board" }).click();
  if (mobile) await page.getByRole("tab", { name: "Engine" }).click();
  await page.getByRole("group", { name: /^Line 1/ }).getByRole("button").first().click();
  await expect(page.getByTestId("variation-banner")).toBeVisible();

  for (const path of ["/games", "/settings"]) {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
  }
  await page.goto("/games");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Export all as PGN" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.pgn$/);

  expect(problems, problems.join("\n")).toEqual([]);
});
