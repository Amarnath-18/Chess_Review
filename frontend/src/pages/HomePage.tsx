import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDeleteGame, useGames, useImport } from "../api/hooks";
import type { ImportResult } from "../api/types";
import { Card } from "../components/Card";
import { StatusChip } from "../components/StatusChip";
import { dateText, gameTitle, resultText, SOURCE_LABEL } from "../lib/format";

function ImportCard() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const importer = useImport();

  const done = (r: ImportResult) => {
    setResult(r);
    const total = r.imported.length + r.duplicates.length;
    if (total === 1 && r.errors.length === 0) {
      const g = r.imported[0] ?? r.duplicates[0].game;
      navigate(`/games/${g.id}`);
    } else if (r.imported.length > 0) {
      setText("");
    }
  };

  const submitText = () => importer.mutate({ text }, { onSuccess: done });
  const onFile = (file?: File) => {
    if (file) importer.mutate({ file }, { onSuccess: done });
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <Card title="Import games">
      <label htmlFor="pgn-text" className="mb-1 block text-sm font-medium">
        Paste PGN
      </label>
      <textarea
        id="pgn-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={'[White "…"]\n[Black "…"]\n\n1. e4 e5 2. Nf3 …'}
        className="w-full rounded border border-slate-300 bg-white p-2 font-mono text-sm dark:border-slate-600 dark:bg-slate-950"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={submitText}
          disabled={!text.trim() || importer.isPending}
          className="rounded bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        >
          {importer.isPending ? "Importing…" : "Import PGN"}
        </button>
        <span className="text-sm text-slate-500">or</span>
        <label className="cursor-pointer rounded border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
          Upload .pgn file
          <input
            ref={fileRef}
            type="file"
            accept=".pgn,.txt,text/plain"
            className="sr-only"
            data-testid="pgn-file"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </label>
      </div>

      {importer.isError && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {(importer.error as Error).message}
        </p>
      )}

      {result && (
        <div className="mt-3 space-y-2 text-sm" aria-live="polite">
          {result.imported.length > 0 && (
            <div>
              <p className="font-semibold text-green-700 dark:text-green-400">
                Imported {result.imported.length} game{result.imported.length > 1 ? "s" : ""}:
              </p>
              <ul className="list-inside list-disc">
                {result.imported.map((g) => (
                  <li key={g.id}>
                    <Link className="text-blue-600 underline dark:text-blue-400" to={`/games/${g.id}`}>
                      {gameTitle(g)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.duplicates.length > 0 && (
            <p className="text-slate-600 dark:text-slate-400">
              {result.duplicates.length} game{result.duplicates.length > 1 ? "s were" : " was"} already in
              your history and not imported again.
            </p>
          )}
          {result.errors.length > 0 && (
            <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
              <p className="font-semibold">
                {result.errors.length} game{result.errors.length > 1 ? "s" : ""} could not be imported:
              </p>
              <ul className="list-inside list-disc">
                {result.errors.map((e) => (
                  <li key={e.index}>{e.message}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function RecentGames() {
  const games = useGames(1, 10);
  const del = useDeleteGame();

  return (
    <Card title="Recent games">
      {games.isLoading && <p role="status" className="text-sm text-slate-500">Loading…</p>}
      {games.isError && (
        <p role="alert" className="text-sm text-red-600">
          Could not load your games: {(games.error as Error).message}
        </p>
      )}
      {games.data && games.data.items.length === 0 && (
        <p className="text-sm text-slate-500">
          No games yet. Paste or upload a PGN above to get started. Your games are kept in this
          browser's session.
        </p>
      )}
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {games.data?.items.map((g) => (
          <li key={g.id} className="flex items-center gap-2 py-2">
            <Link to={`/games/${g.id}`} className="min-w-0 flex-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
              <div className="truncate font-medium">{gameTitle(g)}</div>
              <div className="truncate text-xs text-slate-500">
                {resultText(g.result)} · {dateText(g.played_at)} · {SOURCE_LABEL[g.source] ?? g.source}
                {g.opening_name ? ` · ${g.opening_name}` : ""}
              </div>
            </Link>
            <StatusChip status={g.analysis_status} />
            <button
              type="button"
              aria-label={`Delete ${gameTitle(g)}`}
              onClick={() => {
                if (window.confirm("Delete this game and its analysis? This cannot be undone.")) del.mutate(g.id);
              }}
              className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-950"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function HomePage() {
  return (
    <div className="mx-auto grid max-w-5xl gap-4 px-4 py-4 md:grid-cols-2">
      <ImportCard />
      <RecentGames />
    </div>
  );
}
