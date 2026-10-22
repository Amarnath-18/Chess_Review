import { expect, test, type Page } from "@playwright/test";

const HEADERS = { "X-Requested-With": "ChessReviewLab" };
// Black loses time and blunders late; all of the first moves are opening theory.
const PGN = `[Event "Clocked blitz"]
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

const openTab = async (page: Page, name: string, mobile: boolean) => {
  if (mobile) await page.getByRole("tab", { name }).click();
};

test("clock times, accuracy, opening and annotated PGN", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  const id = await seed(page);
  await page.goto(`/games/${id}`);
  await expect(page.getByTestId("board")).toBeVisible();

  // Clocks need no analysis.
  await openTab(page, "Time", mobile);
  await expect(page.getByTestId("clock-panel")).toBeVisible();
  await expect(page.getByTestId("trouble-black")).toHaveText("4"); // 0:20, 0:15, 0:10, 0:08 are all under 30 s
  await expect(page.getByTestId("trouble-white")).toHaveText("0");
  await page.getByTestId("clock-graph").click({ position: { x: 150, y: 40 } });
  await expect(page.getByTestId("clock-readout")).toContainText("left");
  await page.screenshot({ path: `screenshots/time-${info.project.name}.png`, fullPage: true });

  // Analyze, then check the new review content.
  await page.getByLabel("Search depth").selectOption("10");
  await page.getByRole("button", { name: "Analyze game" }).click();
  await expect(page.getByText(/Stockfish .* depth 10/)).toBeVisible({ timeout: 90_000 });

  await openTab(page, "Summary", mobile);
  const accuracy = await page.getByTestId("accuracy-white").innerText();
  expect(accuracy).toMatch(/^\d{1,3}\.\d%$/);
  expect(await page.getByTestId("count-white-book").innerText()).not.toBe("0"); // opening moves are Book
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Alice vs Bob");
  await expect(page.getByText(/Italian Game/).first()).toBeVisible();

  // The Time section now relates the clock to mistakes (only if there were any).
  await openTab(page, "Time", mobile);
  await expect(page.getByTestId("clock-panel")).toBeVisible();

  // Annotated PGN: a real download with evaluations in it, and the plain one is unchanged.
  const href = await page.getByRole("link", { name: "with analysis" }).getAttribute("href");
  const annotated = await page.request.get(href!);
  expect(annotated.status()).toBe(200);
  const body = await annotated.text();
  expect(body).toContain("[%eval");
  expect(body).toContain("[%clk"); // the clocks survive
  expect(body).toContain('[Annotator "Chess Review Lab');
  const plain = await (await page.request.get(`/api/games/${id}/pgn`)).text();
  expect(plain).not.toContain("[%eval");
  await page.screenshot({ path: `screenshots/richer-review-${info.project.name}.png`, fullPage: true });
});
