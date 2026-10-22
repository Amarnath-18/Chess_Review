import { expect, test } from "@playwright/test";

const live = process.env.E2E_LIVE === "1";

test("the import card offers every source", async ({ page }, info) => {
  await page.goto("/");
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText(["PGN", "Chess.com", "Lichess", "Game link"]);
  await expect(page.getByLabel("Paste PGN")).toBeVisible();
  for (const [name, label] of [
    ["Chess.com", "Chess.com username"],
    ["Lichess", "Lichess username"],
    ["Game link", "Chess.com or Lichess game link"],
  ]) {
    await page.getByRole("tab", { name }).click();
    await expect(page.getByLabel(label)).toBeVisible();
  }
  await page.screenshot({ path: `screenshots/06-import-tabs-${info.project.name}.png`, fullPage: true });
});

test("a bad username is explained before anything is sent", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (r) => r.url().includes("/api/imports/") && requests.push(r.url()));
  await page.goto("/");
  await page.getByRole("tab", { name: "Chess.com" }).click();
  await page.getByLabel("Chess.com username").fill("not valid!");
  await expect(page.getByText(/letters, numbers/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Find games" })).toBeDisabled();
  await page.getByLabel("Chess.com username").fill("ab");
  await expect(page.getByText("Usernames are 3-25 characters.")).toBeVisible();
  expect(requests).toEqual([]);
});

test("the real server refuses links that are not Chess.com or Lichess games", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Game link" }).click();
  await page.getByLabel("Chess.com or Lichess game link").fill("https://evil.example/game/live/183193101523");
  // a Chess.com-looking path on another host: no username box, server must reject it
  await page.getByRole("button", { name: "Import game" }).click();
  await expect(page.getByRole("alert")).toContainText("not a Chess.com or Lichess game link");
  await expect(page.getByText("No games yet")).toBeVisible();
});

test("a Chess.com link asks for the player's username first", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Game link" }).click();
  await page.getByLabel("Chess.com or Lichess game link").fill("https://www.chess.com/game/live/183193101523");
  await expect(page.getByLabel(/username of one of the players/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Import game" })).toBeDisabled();
  await page.getByLabel(/username of one of the players/i).fill("hikaru");
  await expect(page.getByRole("button", { name: "Import game" })).toBeEnabled();
});

test("an unknown account gives a clear message", async ({ page }) => {
  test.skip(!live, "needs internet: set E2E_LIVE=1");
  await page.goto("/");
  await page.getByRole("tab", { name: "Lichess" }).click();
  await page.getByLabel("Lichess username").fill("zz-no-such-user-9q8w");
  await page.getByRole("button", { name: "Find games" }).click();
  await expect(page.getByRole("alert")).toContainText("not found");
});

test("find a public Lichess account's games, import one and open it", async ({ page }, info) => {
  test.skip(!live, "needs internet: set E2E_LIVE=1");
  await page.goto("/");
  await page.getByRole("tab", { name: "Lichess" }).click();
  await page.getByLabel("Lichess username").fill("DrNykterstein");
  await page.getByLabel("Latest games").selectOption("10");
  await page.getByRole("button", { name: "Find games" }).click();

  const found = page.getByTestId("found-games");
  await expect(found).toBeVisible();
  const boxes = found.getByRole("checkbox");
  await expect(boxes.first()).toBeEnabled();
  await page.screenshot({ path: `screenshots/07-found-games-${info.project.name}.png`, fullPage: true });

  await page.getByRole("button", { name: "Clear" }).click();
  await boxes.first().check();
  await page.getByRole("button", { name: "Import 1 selected game" }).click();
  const result = page.getByTestId("import-result");
  await expect(result).toContainText("Imported 1 game");
  await expect(found.getByText("Already imported")).toHaveCount(1);
  await page.screenshot({ path: `screenshots/08-imported-${info.project.name}.png`, fullPage: true });

  await result.getByRole("link").first().click();
  await expect(page.getByTestId("board")).toBeVisible();
  await expect(page.locator("main")).toContainText("Lichess"); // shown as the game source
});

test("the import card never makes the page wider than the screen", async ({ page }) => {
  test.skip(!live, "needs internet: set E2E_LIVE=1");
  await page.goto("/");
  await page.getByRole("tab", { name: "Lichess" }).click();
  await page.getByLabel("Lichess username").fill("DrNykterstein");
  await page.getByRole("button", { name: "Find games" }).click();
  await expect(page.getByTestId("found-games")).toBeVisible();
  // long game rows are truncated; they must not stretch the page
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  // the selection controls are big enough to tap
  for (const name of ["Select all new", "Clear"]) {
    const b = (await page.getByRole("button", { name }).boundingBox())!;
    expect(b.height).toBeGreaterThanOrEqual(44);
  }
});
