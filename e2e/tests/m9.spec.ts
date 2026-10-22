import { expect, test, type Page } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
const game = (white: string, black: string, moves = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5") =>
  `[Event "Casual"]\n[Date "2024.03.09"]\n[White "${white}"]\n[Black "${black}"]\n[Result "1-0"]\n\n${moves} 1-0\n`;

async function seed(page: Page, ...games: string[]): Promise<string[]> {
  await page.request.post("/api/session", { headers: HEADERS });
  // quick settings so analyses finish fast
  await page.request.put("/api/settings", { headers: HEADERS, data: { default_depth: 10, default_multipv: 1 } });
  const ids: string[] = [];
  for (const g of games) {
    const r = await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: g } });
    ids.push((await r.json()).imported[0].id as string);
  }
  return ids;
}

const openTab = async (page: Page, name: string, mobile: boolean) => {
  if (mobile) await page.getByRole("tab", { name }).click();
};

test("favourite, tags and notes: set on a game, found in the list, kept in the export", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  const [a] = await seed(page, game("Alice", "Bob"), game("Cara", "Dan", "1. d4 d5 2. c4 e6 3. Nc3 Nf6"));
  await page.goto(`/games/${a}`);
  await openTab(page, "Notes", mobile);

  await page.getByRole("button", { name: "Mark as favourite" }).click();
  await expect(page.getByRole("button", { name: "Favourite" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("New tag").fill("Italian");
  await page.getByRole("button", { name: "Add tag" }).click();
  await expect(page.getByRole("list", { name: "Tags on this game" })).toContainText("italian");
  await page.getByTestId("game-note").fill("Lost the thread after move 3.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Saved" }).first()).toBeVisible();

  // a note on one move
  await page.getByRole("button", { name: "Next move" }).click();
  await page.getByRole("button", { name: "Next move" }).click();
  await page.getByRole("button", { name: "Next move" }).click();
  await openTab(page, "Notes", mobile);
  await page.getByTestId("move-note").fill("Why not d4?");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("move-note")).toHaveValue("Why not d4?");
  await page.screenshot({ path: `screenshots/notes-${info.project.name}.png`, fullPage: true });

  // the games list shows the marks and can filter by them
  await page.goto("/games");
  await expect(page.getByTestId("result-count")).toHaveText("2 games");
  await page.getByLabel("Favourites only").check();
  await expect(page.getByTestId("result-count")).toHaveText("1 game match");
  const row = page.getByRole("list", { name: "Your marks" });
  await expect(row).toContainText("italian");
  await expect(row).toContainText("Note");
  await page.getByLabel("Favourites only").uncheck();
  await page.getByLabel("Tag").fill("italian");
  await expect(page.getByTestId("result-count")).toHaveText("1 game match");
  await page.screenshot({ path: `screenshots/games-marks-${info.project.name}.png`, fullPage: true });

  // notes travel in the annotated PGN, and the plain one is unchanged
  await page.goto(`/games/${a}`);
  const run = await page.request.post(`/api/games/${a}/analysis`, { headers: HEADERS, data: { depth: 8, multipv: 1 } });
  expect(run.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/games/${a}`)).json()).has_analysis, { timeout: 60_000 }).toBe(true);
  const annotated = await (await page.request.get(`/api/games/${a}/pgn?annotated=true`)).text();
  expect(annotated).toContain("Lost the thread after move 3.");
  expect(annotated).toContain("Why not d4?");
  expect(await (await page.request.get(`/api/games/${a}/pgn`)).text()).not.toContain("Why not d4?");
});

test("analyze all: estimate, progress, result, and cancel", async ({ page }, info) => {
  await seed(
    page,
    game("A1", "B1"),
    game("A2", "B2", "1. d4 d5 2. c4 e6 3. Nc3 Nf6"),
    game("A3", "B3", "1. c4 e5 2. Nc3 Nf6 3. g3 d5"),
  );
  await page.goto("/games");
  const estimate = page.getByTestId("batch-estimate");
  await expect(estimate).toContainText("3 games without a review");
  await expect(estimate).toContainText("depth 10, 1 lines");
  await page.screenshot({ path: `screenshots/batch-offer-${info.project.name}.png`, fullPage: true });

  await page.getByRole("button", { name: "Analyze 3 games" }).click();
  await expect(page.getByTestId("batch-running")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Games analyzed" })).toBeVisible();
  await expect(page.getByTestId("batch-finished")).toContainText("3 analyzed", { timeout: 120_000 });
  await expect(page.getByTestId("batch-estimate")).toHaveCount(0); // nothing left to analyze
  await page.screenshot({ path: `screenshots/batch-done-${info.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByTestId("batch-finished")).toHaveCount(0);

  // cancelling keeps what exists and stops the rest
  await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: game("C1", "D1", "1. e4 c5 2. Nf3 d6 3. d4 cxd4") } });
  await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: game("C2", "D2", "1. e4 e6 2. d4 d5 3. Nc3 Bb4") } });
  await page.reload();
  await page.getByRole("button", { name: "Analyze 2 games" }).click();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("batch-finished")).toContainText("Batch cancelled");
});

test("analyze new games automatically after an import", async ({ page }) => {
  await seed(page);
  await page.request.put("/api/settings", { headers: HEADERS, data: { auto_analyze: true } });
  await page.goto("/");
  await page.getByLabel("Paste PGN").fill(game("E1", "F1") + "\n" + game("E2", "F2", "1. d4 d5 2. c4 e6 3. Nc3 Nf6"));
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByTestId("auto-analyzing")).toContainText("Analyzing 2 of them automatically");
  await page.goto("/games");
  await expect(page.getByTestId("batch-finished")).toContainText("2 analyzed", { timeout: 120_000 });
});

test("a remembered account is listed on the home page", async ({ page }) => {
  await seed(page);
  const r = await page.request.post("/api/sources", { headers: HEADERS, data: { source: "lichess", username: "DrNykterstein" } });
  expect(r.status()).toBe(201);
  await page.goto("/");
  await expect(page.getByTestId("saved-account")).toContainText("DrNykterstein");
  await expect(page.getByRole("button", { name: "Check for new games" })).toBeVisible();
  await page.getByRole("button", { name: "Forget DrNykterstein on Lichess" }).click();
  await expect(page.getByTestId("saved-account")).toHaveCount(0);
});
