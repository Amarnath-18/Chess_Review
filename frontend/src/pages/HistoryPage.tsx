import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { exportUrl } from "../api/client";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDeleteGame, useGames } from "../api/hooks";
import type { GameQuery } from "../api/types";
import { Card } from "../components/Card";
import { CONFIRM_DELETE_GAME, GameListItem } from "../components/GameListItem";

const PAGE_SIZE = 20;
const FILTER_KEYS = ["q", "source", "result", "analyzed", "from", "to"] as const;

const field =
  "w-full rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-950";

function readQuery(p: URLSearchParams): GameQuery & { page: number } {
  const analyzed = p.get("analyzed");
  const sort = p.get("sort");
  return {
    q: p.get("q") ?? "",
    source: p.get("source") ?? "",
    result: p.get("result") ?? "",
    analyzed: analyzed === "yes" || analyzed === "no" ? analyzed : undefined,
    sort: sort === "added" ? "added" : "played",
    from: p.get("from") ?? "",
    to: p.get("to") ?? "",
    page: Math.max(1, parseInt(p.get("page") ?? "1", 10) || 1),
  };
}

/** The filters live in the URL, so a filtered list can be bookmarked and Back works. */
export default function HistoryPage() {
  useDocumentTitle("Your games");
  const [params, setParams] = useSearchParams();
  const query = readQuery(params);
  const games = useGames(query.page, PAGE_SIZE, query);
  const del = useDeleteGame();

  const update = (changes: Record<string, string | null>, keepPage = false) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(changes)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        if (!keepPage) next.delete("page");
        return next;
      },
      { replace: true },
    );

  // Typing in the search box updates the URL after a short pause, not on every keystroke.
  const [search, setSearch] = useState(query.q ?? "");
  useEffect(() => {
    if (search === (query.q ?? "")) return;
    const t = setTimeout(() => update({ q: search.trim() || null }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);
  useEffect(() => setSearch(query.q ?? ""), [query.q]);

  const total = games.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = FILTER_KEYS.some((k) => !!params.get(k));
  const clear = () => {
    setSearch("");
    setParams({}, { replace: true });
  };

  // Deleting the last game on a later page would leave an empty page: step back.
  useEffect(() => {
    if (games.data && games.data.items.length === 0 && query.page > 1 && !games.isFetching)
      update({ page: String(Math.min(query.page - 1, pages)) }, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [games.data, games.isFetching]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-4">
      <h1 className="mb-3 text-xl font-bold">Your games</h1>

      <Card className="mb-4">
        <form
          role="search"
          aria-label="Filter games"
          className="grid grid-cols-2 gap-3 lg:grid-cols-3"
          onSubmit={(e) => e.preventDefault()}
        >
          <label className="col-span-2 text-sm lg:col-span-3">
            <span className="mb-1 block font-medium">Player</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by player name"
              className={field}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Source</span>
            <select value={query.source} onChange={(e) => update({ source: e.target.value || null })} className={field}>
              <option value="">All sources</option>
              <option value="pgn">PGN</option>
              <option value="chesscom">Chess.com</option>
              <option value="lichess">Lichess</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Result</span>
            <select value={query.result} onChange={(e) => update({ result: e.target.value || null })} className={field}>
              <option value="">Any result</option>
              <option value="1-0">White won</option>
              <option value="0-1">Black won</option>
              <option value="1/2-1/2">Draw</option>
              <option value="*">Unknown / unfinished</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Analysis</span>
            <select value={query.analyzed ?? ""} onChange={(e) => update({ analyzed: e.target.value || null })} className={field}>
              <option value="">Analyzed or not</option>
              <option value="yes">Analyzed</option>
              <option value="no">Not analyzed</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Played from</span>
            <input type="date" value={query.from} max={query.to || undefined} onChange={(e) => update({ from: e.target.value || null })} className={field} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Played until</span>
            <input type="date" value={query.to} min={query.from || undefined} onChange={(e) => update({ to: e.target.value || null })} className={field} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Sort by</span>
            <select value={query.sort} onChange={(e) => update({ sort: e.target.value === "added" ? "added" : null })} className={field}>
              <option value="played">Newest played</option>
              <option value="added">Latest imported</option>
            </select>
          </label>
        </form>
        {filtered && (
          <button type="button" onClick={clear} className="mt-3 min-h-11 text-sm text-blue-600 underline dark:text-blue-400">
            Clear all filters
          </button>
        )}
      </Card>

      <Card>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p role="status" className="text-sm text-slate-600 dark:text-slate-400" data-testid="result-count">
            {games.isLoading
              ? "Loading…"
              : `${total} game${total === 1 ? "" : "s"}${filtered ? " match" : ""}`}
          </p>
          {total > 0 ? (
            <a
              href={exportUrl(query)}
              download
              className="inline-flex min-h-11 items-center rounded border border-slate-300 px-3 text-sm font-medium hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              Export {filtered ? "these" : "all"} as PGN
            </a>
          ) : null}
        </div>

        {games.isError && (
          <p role="alert" className="text-sm text-red-600">
            Could not load your games: {(games.error as Error).message}
          </p>
        )}
        {games.data && total === 0 && (
          <div className="py-6 text-center text-sm text-slate-600 dark:text-slate-400">
            {filtered ? (
              <>
                <p>No games match these filters.</p>
                <button type="button" onClick={clear} className="mt-2 min-h-11 text-blue-600 underline dark:text-blue-400">
                  Clear all filters
                </button>
              </>
            ) : (
              <>
                <p>You haven't imported any games yet.</p>
                <Link to="/" className="mt-2 inline-block text-blue-600 underline dark:text-blue-400">
                  Import your first game
                </Link>
              </>
            )}
          </div>
        )}

        <ul className="divide-y divide-slate-200 dark:divide-slate-800" aria-busy={games.isFetching}>
          {games.data?.items.map((g) => (
            <GameListItem
              key={g.id}
              game={g}
              onDelete={(game) => window.confirm(CONFIRM_DELETE_GAME) && del.mutate(game.id)}
            />
          ))}
        </ul>

        {total > PAGE_SIZE && (
          <nav aria-label="Pages" className="mt-3 flex items-center justify-between gap-2">
            <button
              type="button"
              disabled={query.page <= 1}
              onClick={() => update({ page: String(query.page - 1) }, true)}
              className="min-h-11 rounded border border-slate-300 px-3 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              ← Previous
            </button>
            <span className="text-sm text-slate-600 dark:text-slate-400" data-testid="page-info">
              Page {query.page} of {pages}
            </span>
            <button
              type="button"
              disabled={query.page >= pages}
              onClick={() => update({ page: String(query.page + 1) }, true)}
              className="min-h-11 rounded border border-slate-300 px-3 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              Next →
            </button>
          </nav>
        )}
      </Card>
    </div>
  );
}
