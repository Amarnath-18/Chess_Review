import { expect, test, type Page } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
// White (Alice) can mate with 4.Qxf7# but plays 4.d3: a clear, unambiguous mistake.
const PGN = `[Event "Missed mate"]
[White "Alice"]
[Black "Bob"]
[Result "*"]
[TimeControl "300+0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. d3 Bc5 5. Nf3 d6 *
`;

/** An analyzed game in which Alice missed a mate in one. */
async function seed(page: Page): Promise<string> {
  await page.request.post("/api/session", { headers: HEADERS });
  await page.request.put("/api/settings", { headers: HEADERS, data: { default_depth: 12, default_multipv: 3, my_names: ["Alice"] } });
  const r = await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: PGN } });
  const id = (await r.json()).imported[0].id as string;
  const run = await page.request.post(`/api/games/${id}/analysis`, { headers: HEADERS, data: { depth: 12, multipv: 3 } });
  expect(run.status()).toBe(202);
  await expect
    .poll(async () => (await (await page.request.get(`/api/games/${id}`)).json()).has_analysis, { timeout: 90_000 })
    .toBe(true);
  return id;
}

test("a missed mate becomes a puzzle: wrong answer, reveal, then the right one", async ({ page }, info) => {
  await seed(page);
  await page.goto("/train");
  await expect(page.getByRole("heading", { name: "White to move" })).toBeVisible();
  await expect(page.getByTestId("puzzle-prompt")).toBeVisible();
  await expect(page.getByTestId("train-counts")).toContainText("2 puzzles in all");
  await page.screenshot({ path: `screenshots/puzzle-${info.project.name}.png`, fullPage: true });

  await page.getByLabel("Type your move").fill("d3");
  await page.getByRole("button", { name: "Play" }).click();
  const result = page.getByTestId("puzzle-result");
  await expect(result).toContainText("Not quite.");
  await expect(result).toContainText("The engine's choice was Qxf7#");
  await expect(result).toContainText("In the game you played d3");
  await page.screenshot({ path: `screenshots/puzzle-reveal-${info.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: /Next puzzle/ }).click();
  await expect(page.getByTestId("puzzle-prompt")).toBeVisible(); // the next puzzle has loaded
  await page.getByLabel("Type your move").fill("Nf3");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByTestId("puzzle-result")).toBeVisible();
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByTestId("all-done")).toBeVisible(); // misses return in ten minutes, not now

  // the next visit (after the wait) accepts the right move
  const { total } = await (await page.request.get("/api/train")).json();
  expect(total).toBe(2); // 4.d3 and 5.Nf3 both missed the same mate
});

test("the right answer is accepted", async ({ page }) => {
  await seed(page);
  await page.goto("/train");
  await page.getByLabel("Type your move").fill("Qxf7#");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByTestId("puzzle-result")).toContainText("Correct!");
});

test("retry the move in the review", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  const id = await seed(page);
  await page.goto(`/games/${id}`);
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next move" }).click();
  await expect(page.getByTestId("current-move")).toContainText("4. d3");
  if (mobile) await page.getByRole("tab", { name: "Engine" }).click();
  await page.getByRole("button", { name: "Try to find a better move" }).click();
  const banner = page.getByTestId("retry-banner");
  await expect(banner).toContainText("Find a better move than d3");

  await page.getByLabel("Type your move").fill("Nf3");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(banner).toContainText(/Not (quite|judged)/);
  await page.getByRole("button", { name: "Show the answer" }).click();
  await expect(page.getByTestId("retry-answer")).toContainText("Qxf7#");
  await page.getByRole("button", { name: "Try again" }).click();
  await page.getByLabel("Type your move").fill("Qxf7#");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(banner).toContainText("Found it");
  await page.screenshot({ path: `screenshots/retry-${info.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: /Back to the game/ }).click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByTestId("current-move")).toContainText("4. d3");
});

test("statistics are about me, and honest about how little data there is", async ({ page }, info) => {
  await seed(page);
  await page.goto("/stats");
  await expect(page.getByTestId("stats-basis")).toContainText("Based on 1 analyzed game");
  await expect(page.getByTestId("bucket-opening")).toContainText("too few moves to conclude");
  await expect(page.getByText(/is called a weakness until there is enough data/)).toBeVisible();
  await expect(page.getByTestId("opening-row").first()).toContainText("too few games");
  await page.screenshot({ path: `screenshots/stats-${info.project.name}.png`, fullPage: true });
});

test("without names there is nothing to attribute", async ({ page }) => {
  await page.request.post("/api/session", { headers: HEADERS });
  await page.goto("/train");
  await expect(page.getByText(/needs to know which player you are/)).toBeVisible();
  await page.goto("/stats");
  await expect(page.getByText(/needs to know which player you are/)).toBeVisible();
  // ...and the settings page is where to say who you are
  await page.goto("/settings");
  await page.getByLabel("Your player names").fill("Alice, Magnus");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Your player names")).toHaveValue("Alice, Magnus");
});
