import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { mockApi } from "./test/render";

afterEach(() => vi.unstubAllGlobals());

function open(path = "/", extra?: (c: { method: string; url: string; body?: unknown }) => { status?: number; body?: unknown } | undefined) {
  mockApi((c) => {
    const special = extra?.(c);
    if (special) return special;
    if (c.url === "/api/settings")
      return { body: { default_depth: 16, default_multipv: 3, import_count: 20, max_depth: 22, max_multipv: 5, retention_days: 30 } };
    if (c.url.startsWith("/api/games?")) return { body: { items: [], total: 0, page: 1, page_size: 20 } };
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("navigation", () => {
  it("links to every main page", () => {
    open();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(Array.from(nav.querySelectorAll("a")).map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Import", "/"],
      ["Games", "/games"],
      ["Train", "/train"],
      ["Stats", "/stats"],
      ["Settings", "/settings"],
    ]);
  });

  it.each([
    ["/", "Import"],
    ["/games", "Games"],
    ["/settings", "Settings"],
  ])("marks %s as the current page", (path, name) => {
    open(path);
    expect(screen.getByRole("link", { name, current: "page" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { current: "page" })).toHaveLength(1);
  });

  it("moves between the pages", async () => {
    open();
    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "Games" }));
    expect(await screen.findByRole("heading", { name: "Your games" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Chess Review Lab/ }));
    expect(await screen.findByLabelText("Paste PGN")).toBeInTheDocument();
  });

  it("shows a friendly page for unknown addresses", async () => {
    open("/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });

  it("the nav controls are big enough to tap", () => {
    open();
    for (const a of screen.getByRole("navigation", { name: "Main" }).querySelectorAll("a"))
      expect(a.className).toContain("min-h-11");
  });
});

describe("private server", () => {
  it("shows the invite page instead of the app until a code is accepted", async () => {
    let unlocked = false;
    open("/games", (c) => {
      if (c.url === "/api/access" && c.method === "GET") return { body: { required: true, unlocked, label: null } };
      if (c.url === "/api/access" && c.method === "POST") {
        if ((c.body as { code: string }).code !== "good-code") return { status: 403, body: { detail: "That code is not valid." } };
        unlocked = true;
        return { body: { required: true, unlocked: true, label: "Alice" } };
      }
    });
    expect(await screen.findByRole("heading", { name: "Enter your invite code" })).toBeInTheDocument();
    expect(screen.queryByText("Your games")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Invite code"), "wrong");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not valid.");

    await user.clear(screen.getByLabelText("Invite code"));
    await user.type(screen.getByLabelText("Invite code"), "good-code");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Your games" })).toBeInTheDocument();
  });

  it("does not ask for a code on an open server", async () => {
    open("/games", (c) => (c.url === "/api/access" ? { body: { required: false, unlocked: true, label: null } } : undefined));
    expect(await screen.findByRole("heading", { name: "Your games" })).toBeInTheDocument();
  });
});
