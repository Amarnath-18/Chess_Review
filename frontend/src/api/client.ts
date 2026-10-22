import type {
  Analysis,
  AnalysisStart,
  GameDetail,
  GameList,
  ExternalSource,
  GameQuery,
  ImportResult,
  Job,
  PreviewResult,
  Settings,
  SettingsPatch,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

const CSRF = { "X-Requested-With": "ChessReviewLab" };

function messageFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length > 0) {
      const first = d[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
  }
  return fallback;
}

let sessionReady: Promise<void> | null = null;

/** Creates (or confirms) the anonymous session cookie. Safe to call repeatedly. */
export function ensureSession(force = false): Promise<void> {
  if (!sessionReady || force) {
    sessionReady = fetch("/api/session", { method: "POST", headers: CSRF })
      .then((r) => {
        if (!r.ok) throw new ApiError(r.status, "Could not start a session");
      })
      .catch((e) => {
        sessionReady = null; // allow a later retry
        throw e;
      });
  }
  return sessionReady;
}

async function request<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  await ensureSession();
  const headers: Record<string, string> = { ...CSRF, ...(init.headers as Record<string, string>) };
  if (init.body && typeof init.body === "string") headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && !retried) {
    await ensureSession(true); // cookie expired or was cleared
    return request<T>(path, init, true);
  }
  if (res.status === 204) return undefined as T;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (!res.ok) throw new ApiError(res.status, messageFrom(body, res.statusText), body);
  return body as T;
}

/** Query string for the games list / export. Empty values are left out. */
export function gameQueryString(query: GameQuery, extra: Record<string, string | number> = {}) {
  const p = new URLSearchParams();
  if (query.q?.trim()) p.set("q", query.q.trim());
  if (query.source) p.set("source", query.source);
  if (query.result) p.set("result", query.result);
  if (query.analyzed) p.set("analyzed", query.analyzed === "yes" ? "true" : "false");
  if (query.sort && query.sort !== "played") p.set("sort", query.sort);
  if (query.from) p.set("date_from", query.from);
  if (query.to) p.set("date_to", query.to);
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const exportUrl = (query: GameQuery) => `/api/games/export${gameQueryString(query)}`;
export const gamePgnUrl = (id: string) => `/api/games/${id}/pgn`;

const json = (data: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(data) });

export const api = {
  listGames: (page = 1, pageSize = 10, query: GameQuery = {}) =>
    request<GameList>(`/api/games${gameQueryString(query, { page, page_size: pageSize })}`),
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (patch: SettingsPatch) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  deleteAllGames: () => request<{ deleted: number }>("/api/me/games", { method: "DELETE" }),
  deleteEverything: () => request<void>("/api/me", { method: "DELETE" }),
  getGame: (id: string) => request<GameDetail>(`/api/games/${id}`),
  deleteGame: (id: string) => request<void>(`/api/games/${id}`, { method: "DELETE" }),
  getAnalysis: (id: string) => request<Analysis>(`/api/games/${id}/analysis`),
  startAnalysis: (id: string, body: { depth?: number; nodes?: number; multipv?: number }) =>
    request<AnalysisStart>(`/api/games/${id}/analysis`, json(body)),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  retryJob: (id: string) => request<AnalysisStart>(`/api/jobs/${id}/retry`, { method: "POST" }),

  /** Import PGN text. A 422 with per-game errors is returned as a result, not thrown. */
  async importPgn(pgnText: string): Promise<ImportResult> {
    try {
      return await request<ImportResult>("/api/imports/pgn", json({ pgn_text: pgnText }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && isImportResult(e.body)) return e.body;
      throw e;
    }
  },
  /** Look up a user's recent games on Chess.com or Lichess (nothing is saved). */
  previewGames: (source: ExternalSource, username: string, maxGames: number) =>
    request<PreviewResult>(
      "/api/imports/preview",
      json({ source, username, max_games: maxGames }),
    ),
  /** Import the games picked from a preview. Per-game problems come back as a result. */
  async commitGames(
    source: ExternalSource,
    username: string,
    externalIds: string[],
  ): Promise<ImportResult> {
    try {
      return await request<ImportResult>(
        "/api/imports/commit",
        json({ source, username, external_ids: externalIds }),
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && isImportResult(e.body)) return e.body;
      throw e;
    }
  },
  async importFromLink(url: string, usernameHint?: string): Promise<ImportResult> {
    try {
      return await request<ImportResult>(
        "/api/imports/url",
        json({ url, username_hint: usernameHint || null }),
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && isImportResult(e.body)) return e.body;
      throw e;
    }
  },
  async importPgnFile(file: File): Promise<ImportResult> {
    const form = new FormData();
    form.append("file", file);
    try {
      return await request<ImportResult>("/api/imports/pgn/upload", { method: "POST", body: form });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && isImportResult(e.body)) return e.body;
      throw e;
    }
  },
};

function isImportResult(b: unknown): b is ImportResult {
  return !!b && typeof b === "object" && "errors" in b && "imported" in b;
}
