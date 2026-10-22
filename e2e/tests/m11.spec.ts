import { expect, test, type Page } from "@playwright/test";

// Needs the api to be pointed at e2e/fake_llm.py (see README, "AI explanations" under Testing):
//   E2E_LLM=1 docker compose run --rm -e E2E_LLM=1 e2e npx playwright test m11.spec.ts
test.skip(!process.env.E2E_LLM, "needs the fake explanation model (E2E_LLM=1)");

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
const PGN = `[Event "Missed mate"]
[White "Alice"]
[Black "Bob"]
[Result "*"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. d3 Bc5 5. Nf3 d6 *
`;

async function seed(page: Page): Promise<string> {
  await page.request.post("/api/session", { headers: HEADERS });
  const r = await page.request.post("/api/imports/pgn", { headers: HEADERS, data: { pgn_text: PGN } });
  const id = (await r.json()).imported[0].id as string;
  await page.request.post(`/api/games/${id}/analysis`, { headers: HEADERS, data: { depth: 12, multipv: 3 } });
  await expect
    .poll(async () => (await (await page.request.get(`/api/games/${id}`)).json()).has_analysis, { timeout: 90_000 })
    .toBe(true);
  return id;
}

const openTab = async (page: Page, name: string, mobile: boolean) => {
  if (mobile) await page.getByRole("tab", { name }).click();
};

test("off by default; opt in from Settings; explain a move; label and engine line are shown", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  const id = await seed(page);

  // 1. nothing is offered until the person opts in
  await page.goto(`/games/${id}`);
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next move" }).click();
  await openTab(page, "Engine", mobile);
  await expect(page.getByRole("link", { name: "Turn them on in Settings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explain this move" })).toHaveCount(0);

  // 2. the notice says who receives what; opt in and pick a level
  await page.goto("/settings");
  await expect(page.getByTestId("ai-notice")).toContainText("never names or whole games");
  await expect(page.getByTestId("ai-notice")).toContainText("Nothing leaves it"); // a model on this network
  await page.getByRole("checkbox", { name: /Explain moves with AI/ }).check();
  await page.getByLabel("Explain at the level of a").selectOption("beginner");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.screenshot({ path: `screenshots/ai-settings-${info.project.name}.png`, fullPage: true });

  // 3. explain the move; the AI label and the engine's own line sit next to the text
  await page.goto(`/games/${id}`);
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next move" }).click();
  await openTab(page, "Engine", mobile);
  await page.getByRole("button", { name: "Explain this move" }).click();
  await expect(page.getByTestId("ai-text")).toContainText("You played d3, but the engine preferred Qxf7#");
  await expect(page.getByTestId("explain-box").getByTestId("ai-note")).toContainText("Written by an AI");
  await expect(page.getByRole("group", { name: "Engine line behind the explanation" })).toContainText("Qxf7#");
  await page.screenshot({ path: `screenshots/ai-explanation-${info.project.name}.png`, fullPage: true });

  // 4. asking again is instant: it survives a reload and is not asked of the model again
  await page.reload();
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next move" }).click();
  await openTab(page, "Engine", mobile);
  await expect(page.getByTestId("ai-text")).toContainText("Qxf7#");
  const usage = await (await page.request.get(`/api/games/${id}/explanations`)).json();
  expect(usage.items).toHaveLength(1);
  expect(usage.items[0].level).toBe("beginner");
});

test("key moments are explained in one go, each labelled", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  const id = await seed(page);
  await page.request.put("/api/settings", { headers: HEADERS, data: { ai_explanations: true } });
  await page.goto(`/games/${id}`);
  await openTab(page, "Summary", mobile);
  const moments = page.getByTestId("key-moments");
  await moments.getByRole("button", { name: /Explain \d+ key moment/ }).click();
  await expect(moments.getByTestId("ai-note").first()).toContainText("Written by an AI");
  await expect(moments.getByRole("button", { name: /Explain \d+ key moment/ })).toHaveCount(0);
  await page.screenshot({ path: `screenshots/ai-key-moments-${info.project.name}.png`, fullPage: true });
});

test("a model that invents a move never reaches the screen: the plain summary is shown", async ({ page }) => {
  // asked to write for an "advanced" player, the fake model names a move that is not in the engine data
  const id = await seed(page);
  await page.request.put("/api/settings", { headers: HEADERS, data: { ai_explanations: true, explain_level: "advanced" } });
  const r = await page.request.post(`/api/games/${id}/explain/7`, { headers: HEADERS });
  const body = await r.json();
  expect(body.source).toBe("fallback");
  expect(body.text).not.toContain("Qh5");
  expect(body.text).toContain("You played d3");

  await page.goto(`/games/${id}`);
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next move" }).click();
  if (page.viewportSize()!.width < 1024) await page.getByRole("tab", { name: "Engine" }).click();
  await expect(page.getByTestId("explain-box").getByTestId("ai-note")).toContainText("could not be verified");
});
