import { expect, test, type Page } from "@playwright/test";

const PGN = `[Event "Italian, short"]
[White "Alice"]
[Black "Bob"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 6. cxd4 Bb4+ 7. Nc3 Nxe4 8. O-O Nxc3 9. bxc3 Bxc3 10. Ba3 *
`;

/** Drag a piece between squares. Phones use touch events, desktops use the mouse. */
async function dragPiece(page: Page, from: string, to: string, mobile: boolean) {
  const src = page.locator(`[data-square="${from}"]`);
  const dst = page.locator(`[data-square="${to}"]`);
  if (!mobile) return src.dragTo(dst);
  await page.getByTestId("board").scrollIntoViewIfNeeded(); // touch coordinates are viewport-relative
  const a = (await src.boundingBox())!;
  const b = (await dst.boundingBox())!;
  const p = (box: typeof a) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
  const cdp = await page.context().newCDPSession(page);
  const touch = (type: string, pt?: { x: number; y: number }) =>
    cdp.send("Input.dispatchTouchEvent", { type, touchPoints: pt ? [pt] : [] });
  await touch("touchStart", p(a));
  await page.waitForTimeout(100); // the touch backend ignores instantaneous gestures
  for (let i = 1; i <= 10; i++) {
    await touch("touchMove", {
      x: p(a).x + ((p(b).x - p(a).x) * i) / 10,
      y: p(a).y + ((p(b).y - p(a).y) * i) / 10,
    });
    await page.waitForTimeout(30);
  }
  await touch("touchEnd");
}

const shot = (page: Page, name: string, project: string) =>
  page.screenshot({ path: `screenshots/${name}-${project}.png`, fullPage: true });

async function importAndAnalyze(page: Page) {
  await page.goto("/");
  await page.getByLabel("Paste PGN").fill(PGN);
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByRole("heading", { name: "Alice vs Bob" })).toBeVisible();
  await page.getByLabel("Search depth").selectOption("10");
  await page.getByLabel("Engine lines").selectOption("4");
  await page.getByRole("button", { name: "Analyze game" }).click();
  await expect(page.getByText("Analysis complete").or(page.getByRole("progressbar"))).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-analyze" }).or(page.getByText(/Stockfish .* depth 10/))).toBeVisible({
    timeout: 90_000,
  });
}

async function openTab(page: Page, name: string, mobile: boolean) {
  if (mobile) await page.getByRole("tab", { name }).click();
}

test("import, analyze and review a game", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  await page.goto("/");
  await shot(page, "01-home-empty", info.project.name);

  await importAndAnalyze(page);
  await expect(page.getByTestId("board")).toBeVisible();

  // --- AT-05: the real board follows the move list
  await openTab(page, "Moves", mobile);
  await page.getByRole("group", { name: "Moves" }).getByRole("button", { name: /^Nf3/ }).click();
  await expect(page.locator('[data-square="f3"] [data-piece="wN"]')).toBeVisible();
  await expect(page.getByTestId("current-move")).toContainText("2. Nf3");

  // every move is marked on the board, on the square it moved to
  const mark = page.getByTestId("move-mark");
  await expect(mark).toBeVisible();
  await expect(mark).toHaveAttribute("data-square", "f3");
  await expect(mark).toHaveAttribute(
    "data-class",
    /^(brilliant|great|best|excellent|good|inaccuracy|mistake|blunder)$/,
  );
  await page.getByRole("button", { name: "First move" }).click();
  await expect(mark).toHaveCount(0); // nothing has been played yet
  await page.getByRole("group", { name: "Moves" }).getByRole("button", { name: /^Nf3/ }).click();
  await expect(mark).toBeVisible();

  await page.getByRole("button", { name: "Last move" }).click();
  await expect(page.getByTestId("current-move")).toContainText("10. Ba3");
  await expect(page.locator('[data-square="a3"] [data-piece="wB"]')).toBeVisible();
  await page.getByRole("button", { name: "First move" }).click();
  await expect(page.locator('[data-square="e2"] [data-piece="wP"]')).toBeVisible();

  if (!mobile) {
    await page.keyboard.press("ArrowRight");
    await expect(page.locator('[data-square="e4"] [data-piece="wP"]')).toBeVisible();
  }

  // --- AT-06: clicking the graph selects the matching move
  await openTab(page, "Graph", mobile);
  const graph = page.getByTestId("eval-graph");
  const box = (await graph.boundingBox())!;
  await page.mouse.click(box.x + box.width * (10 / 19), box.y + box.height / 2); // ply 10 of 19
  await expect(page.getByTestId("graph-cursor")).toHaveAttribute("data-ply", "10");
  await expect(page.getByTestId("current-move")).toContainText("5... exd4");

  // --- engine + summary content
  await openTab(page, "Engine", mobile);
  await expect(page.getByTestId("engine-panel")).toBeVisible();

  // several engine lines, and the user picks how many to see (4 were analyzed)
  const lines = page.getByTestId("engine-lines").getByRole("listitem");
  await expect(lines).toHaveCount(3);
  const picker = page.getByRole("group", { name: "Engine lines shown" });
  await expect(picker.getByRole("button")).toHaveCount(4);
  await picker.getByRole("button", { name: "4" }).click();
  await expect(lines).toHaveCount(4);
  await shot(page, "02b-four-lines", info.project.name);
  await picker.getByRole("button", { name: "1" }).click();
  await expect(lines).toHaveCount(1);
  await picker.getByRole("button", { name: "3" }).click();
  await expect(lines).toHaveCount(3);
  await openTab(page, "Summary", mobile);
  await expect(page.getByText("Analysis complete")).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await shot(page, "02-review-summary", info.project.name);

  // --- variations: drag a real piece, nothing is saved, Esc returns
  await openTab(page, "Engine", mobile);
  await page.getByRole("button", { name: "First move" }).click();
  await expect(page.getByTestId("current-move")).toContainText("Start position");
  await expect(page.locator('[data-square="d2"] [data-piece="wP"]')).toBeVisible();
  await page.waitForTimeout(500); // let the piece-slide animation finish before dragging
  const before = await page.getByTestId("board").getAttribute("data-fen");
  await dragPiece(page, "d2", "d4", mobile);
  await expect(page.getByTestId("variation-banner")).toBeVisible();
  await expect(page.locator('[data-square="d4"] [data-piece="wP"]')).toBeVisible();
  await shot(page, "03-variation", info.project.name);
  await page.getByRole("button", { name: /Return to game/ }).click();
  await expect(page.getByTestId("variation-banner")).toHaveCount(0);
  await expect(page.getByTestId("board")).toHaveAttribute("data-fen", before!);

  // reload: the saved review is still there and untouched by the variation
  await page.reload();
  await expect(page.getByRole("heading", { name: "Alice vs Bob" })).toBeVisible();
  await openTab(page, "Summary", mobile);
  await expect(page.getByText("Analysis complete")).toBeVisible();
});

test("layout is usable at this screen size", async ({ page }, info) => {
  const mobile = info.project.name === "mobile";
  await importAndAnalyze(page);

  // no horizontal scrolling of the page
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  // the board fits the viewport
  const board = (await page.getByTestId("board").boundingBox())!;
  const vw = page.viewportSize()!.width;
  expect(board.width).toBeGreaterThan(Math.min(250, vw * 0.6));
  expect(board.x + board.width).toBeLessThanOrEqual(vw);

  // AT-14: core controls are touch-sized
  for (const name of ["First move", "Previous move", "Next move", "Last move", "Flip board"]) {
    const b = (await page.getByRole("button", { name }).boundingBox())!;
    expect(b.height).toBeGreaterThanOrEqual(44);
    expect(b.width).toBeGreaterThanOrEqual(40);
  }
  if (mobile) {
    await expect(page.getByRole("tablist")).toBeVisible();
    for (const t of ["Moves", "Graph", "Engine", "Summary"]) {
      await page.getByRole("tab", { name: t }).click();
      await expect(page.getByRole("tab", { name: t })).toHaveAttribute("aria-selected", "true");
    }
  }
  await page.getByRole("button", { name: "Next move" }).click();
  await page.getByRole("button", { name: "Next move" }).click();
  await shot(page, "04-review", info.project.name);
});

test("a malformed PGN shows a clear error and saves nothing", async ({ page }, info) => {
  await page.goto("/");
  await page.getByLabel("Paste PGN").fill("1. e4 e5 2. Ke3 *");
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByRole("alert")).toContainText("Ke3");
  await expect(page.getByText("No games yet")).toBeVisible();
  await shot(page, "05-import-error", info.project.name);
});

test("another browser session cannot open my game", async ({ page, browser }) => {
  await page.goto("/");
  await page.getByLabel("Paste PGN").fill(PGN);
  await page.getByRole("button", { name: "Import PGN" }).click();
  await expect(page.getByRole("heading", { name: "Alice vs Bob" })).toBeVisible();
  const url = page.url();

  const other = await browser.newContext();
  const p2 = await other.newPage();
  await p2.goto(url);
  await expect(p2.getByText("Game not found")).toBeVisible();
  await other.close();
});
