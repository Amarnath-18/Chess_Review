import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import ReviewPage from "../pages/ReviewPage";

export interface Call {
  method: string;
  url: string;
  body?: unknown;
}

type Handler = (call: Call) => { status?: number; body?: unknown } | undefined;

/** Replaces global fetch. Every request is recorded in `calls`. */
export function mockApi(handler: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = {
        method: init?.method ?? "GET",
        url,
        body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      };
      calls.push(call);
      if (url === "/api/session") return json(200, { new: false });
      const res = handler(call) ?? { status: 404, body: { detail: "not mocked" } };
      return json(res.status ?? 200, res.body);
    }),
  );
  return calls;
}

function json(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as Response;
}

/** Query parameters of a recorded request. */
export const paramsOf = (call: Call) => new URL(call.url, "http://x").searchParams;

/** Render any set of routes with a fresh query client. */
export function renderAt(initial: string, routes: { path: string; element: React.ReactElement }[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          {routes.map((r) => (
            <Route key={r.path} path={r.path} element={r.element} />
          ))}
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function renderReview(gameId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/games/${gameId}`]}>
        <Routes>
          <Route path="/games/:id" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
