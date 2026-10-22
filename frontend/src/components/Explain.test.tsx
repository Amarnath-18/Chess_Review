import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Explanation, Settings } from "../api/types";
import { makeAnalysis } from "../test/fixtures";
import { type Call, mockApi, renderAt } from "../test/render";
import { ExplainBox } from "./ExplainBox";
import { KeyMoments } from "./KeyMoments";

afterEach(() => vi.unstubAllGlobals());

const SETTINGS: Settings = {
  default_depth: 16, default_multipv: 3, import_count: 20, max_depth: 22, max_multipv: 5, retention_days: 30,
  ai_available: true, ai_explanations: true, ai_provider: "OpenRouter", explain_daily_limit: 30,
};

const explanation = (ply: number, over: Partial<Explanation> = {}): Explanation => ({
  ply, text: `Explanation for ply ${ply}.`, source: "ai", motif: null, model: "m", level: "intermediate",
  cached: false, remaining_today: 29, created_at: "2024-03-10T00:00:00Z", ...over,
});

/** A server whose explanations list grows as explanations are made. */
function serve(opts: { settings?: Partial<Settings>; stored?: Explanation[]; failAt?: { ply: number; status: number; detail: string } } = {}) {
  const store = [...(opts.stored ?? [])];
  const calls: Call[] = mockApi((c) => {
    if (c.url === "/api/settings") return { body: { ...SETTINGS, ...opts.settings } };
    if (c.url === "/api/games/g1/explanations") return { body: { items: store, remaining_today: 29 - store.length } };
    const m = c.url.match(/^\/api\/games\/g1\/explain\/(\d+)$/);
    if (m && c.method === "POST") {
      const ply = Number(m[1]);
      if (opts.failAt && opts.failAt.ply === ply) return { status: opts.failAt.status, body: { detail: opts.failAt.detail } };
      const made = explanation(ply, { remaining_today: 28 });
      store.push(made);
      return { body: made };
    }
  });
  return { calls, store };
}

const analysis = makeAnalysis();
const previous = analysis.positions[4];
const explainCalls = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url.includes("/explain/"));

const box = (ply = 5) =>
  renderAt("/", [{ path: "/", element: <ExplainBox gameId="g1" ply={ply} previous={previous} onExplore={vi.fn()} /> }]);

describe("explain this move", () => {
  it("is invisible when the server has no model", async () => {
    serve({ settings: { ai_available: false } });
    box();
    await waitFor(() => expect(screen.queryByTestId("explain-box")).not.toBeInTheDocument());
    expect(screen.queryByText(/Turn them on/)).not.toBeInTheDocument();
  });

  it("only points to Settings until the person opts in, and sends nothing", async () => {
    const { calls } = serve({ settings: { ai_explanations: false } });
    box();
    expect(await screen.findByRole("link", { name: "Turn them on in Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: "Explain this move" })).not.toBeInTheDocument();
    expect(explainCalls(calls)).toHaveLength(0);
  });

  it("explains on request, labels the text as AI-written, and shows the engine line beside it", async () => {
    const { calls } = serve();
    box();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Explain this move" }));
    expect(await screen.findByTestId("ai-text")).toHaveTextContent("Explanation for ply 5.");
    expect(explainCalls(calls)).toHaveLength(1);
    expect(screen.getByTestId("ai-note")).toHaveTextContent("Written by an AI from the engine's analysis. It can be wrong");
    const line = screen.getByRole("group", { name: "Engine line behind the explanation" });
    expect(line).toHaveTextContent("e4"); // the engine's own line, next to the claim
    expect(screen.queryByRole("button", { name: "Explain this move" })).not.toBeInTheDocument();
  });

  it("shows an explanation that already exists without asking again", async () => {
    const { calls } = serve({ stored: [explanation(5)] });
    box();
    expect(await screen.findByTestId("ai-text")).toHaveTextContent("Explanation for ply 5.");
    expect(explainCalls(calls)).toHaveLength(0);
  });

  it("is honest when the AI's answer could not be verified", async () => {
    serve({ stored: [explanation(5, { source: "fallback", text: "You played Bc4." })] });
    box();
    expect(await screen.findByTestId("ai-note")).toHaveTextContent("could not be verified");
    expect(screen.getByTestId("ai-text")).toHaveTextContent("You played Bc4.");
  });

  it("shows why it could not explain (limit reached)", async () => {
    serve({ failAt: { ply: 5, status: 429, detail: "You have used today's 30 explanations. Try again tomorrow." } });
    box();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Explain this move" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("used today's 30 explanations");
    expect(screen.getByRole("button", { name: "Explain this move" })).toBeInTheDocument(); // can try again later
  });
});

const moments = (plies = [2, 3, 5]) =>
  renderAt("/", [{ path: "/", element: <KeyMoments gameId="g1" plies={plies} moveLabel={(p) => `move ${p}`} onSelectPly={vi.fn()} /> }]);

describe("explain key moments", () => {
  it("explains only what is missing, one after another", async () => {
    const { calls } = serve({ stored: [explanation(3)] });
    moments();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Explain 2 key moments" }));
    await waitFor(() => expect(explainCalls(calls).map((c) => c.url)).toEqual(["/api/games/g1/explain/2", "/api/games/g1/explain/5"]));
    expect(await screen.findByText("Explanation for ply 5.")).toBeInTheDocument();
    expect(screen.getAllByTestId("ai-note")).toHaveLength(3); // every explanation carries its label
    expect(screen.queryByRole("button", { name: /Explain \d key moment/ })).not.toBeInTheDocument();
  });

  it("stops at the first problem and keeps what it already made", async () => {
    const { calls } = serve({ failAt: { ply: 3, status: 502, detail: "The explanation model could not be reached." } });
    moments();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Explain 3 key moments" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");
    expect(explainCalls(calls).map((c) => c.url)).toEqual(["/api/games/g1/explain/2", "/api/games/g1/explain/3"]); // ply 5 never asked
    expect(await screen.findByText("Explanation for ply 2.")).toBeInTheDocument();
  });

  it("is hidden when AI explanations are off, and caps at eight moments", async () => {
    serve({ settings: { ai_explanations: false } });
    const first = moments();
    await waitFor(() => expect(screen.queryByTestId("key-moments")).not.toBeInTheDocument());
    first.unmount();

    serve();
    moments([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(await screen.findByRole("button", { name: "Explain 8 key moments" })).toBeInTheDocument();
  });
});
