import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useCommitGames, useImport, useImportLink, usePreviewGames, useSettings } from "../api/hooks";
import type { ExternalSource, ImportResult, PreviewGame, PreviewResult } from "../api/types";
import { dateText, gameTitle, playerLabel, resultText } from "../lib/format";
import { Card } from "./Card";

type Tab = "pgn" | "chesscom" | "lichess" | "link";
const TABS: { id: Tab; label: string }[] = [
  { id: "pgn", label: "PGN" },
  { id: "chesscom", label: "Chess.com" },
  { id: "lichess", label: "Lichess" },
  { id: "link", label: "Game link" },
];

const SOURCE_NAME: Record<ExternalSource, string> = { chesscom: "Chess.com", lichess: "Lichess" };

/** Same rules as the server (which stays the authority); this only gives quicker feedback. */
export function usernameProblem(source: ExternalSource, raw: string): string | null {
  const name = raw.trim();
  if (!name) return null; // empty: just keep the button disabled
  const [min, max] = source === "chesscom" ? [3, 25] : [2, 30];
  if (!/^[A-Za-z0-9_-]+$/.test(name)) return "Use letters, numbers, '-' and '_' only.";
  if (name.length < min || name.length > max) return `Usernames are ${min}-${max} characters.`;
  return null;
}

const inputCls =
  "w-full rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-950";
const primaryBtn =
  "rounded bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700";

export function ImportResultView({ result }: { result: ImportResult }) {
  return (
    <div className="mt-3 space-y-2 text-sm" aria-live="polite" data-testid="import-result">
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
          {result.duplicates.length} game{result.duplicates.length > 1 ? "s were" : " was"} already
          in your history and not imported again.
        </p>
      )}
      {result.errors.length > 0 && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-2 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
        >
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
  );
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
      {(error as Error).message}
    </p>
  );
}

// ---- PGN ---------------------------------------------------------------------------------

function PgnImport() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const importer = useImport();

  const done = (r: ImportResult) => {
    setResult(r);
    const total = r.imported.length + r.duplicates.length;
    if (total === 1 && r.errors.length === 0) {
      navigate(`/games/${(r.imported[0] ?? r.duplicates[0].game).id}`);
    } else if (r.imported.length > 0) setText("");
  };

  return (
    <div>
      <label htmlFor="pgn-text" className="mb-1 block text-sm font-medium">
        Paste PGN
      </label>
      <textarea
        id="pgn-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={'[White "…"]\n[Black "…"]\n\n1. e4 e5 2. Nf3 …'}
        className={`${inputCls} font-mono`}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => importer.mutate({ text }, { onSuccess: done })}
          disabled={!text.trim() || importer.isPending}
          className={primaryBtn}
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
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importer.mutate({ file }, { onSuccess: done });
              if (fileRef.current) fileRef.current.value = "";
            }}
          />
        </label>
      </div>
      <ErrorLine error={importer.error} />
      {result && <ImportResultView result={result} />}
    </div>
  );
}

// ---- Chess.com / Lichess by username -------------------------------------------------------

function GameRow({
  game,
  checked,
  onToggle,
}: {
  game: PreviewGame;
  checked: boolean;
  onToggle: () => void;
}) {
  const disabled = !game.importable || game.already_imported;
  const title = `${playerLabel(game.white, game.white_elo)} vs ${playerLabel(game.black, game.black_elo)}`;
  return (
    <li className={`flex min-w-0 items-start gap-2 py-2 ${disabled ? "opacity-60" : ""}`}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4"
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
        aria-label={`Select ${title}`}
        data-testid={`pick-${game.external_id}`}
      />
      <div className="min-w-0 flex-1 text-sm">
        <div className="truncate font-medium">{title}</div>
        <div className="truncate text-xs text-slate-500">
          {resultText(game.result)} · {dateText(game.played_at)}
          {game.time_control ? ` · ${game.time_control}` : ""}
          {game.ply_count ? ` · ${Math.ceil(game.ply_count / 2)} moves` : ""}
          {game.opening_name ? ` · ${game.opening_name}` : ""}
        </div>
        {game.already_imported && (
          <span className="mt-0.5 inline-block rounded bg-slate-200 px-1.5 text-xs font-semibold dark:bg-slate-700">
            Already imported
          </span>
        )}
        {!game.importable && (
          <span className="mt-0.5 inline-block text-xs text-red-600 dark:text-red-400">
            Can't import: {game.problem}
          </span>
        )}
      </div>
    </li>
  );
}

function UsernameImport({ source }: { source: ExternalSource }) {
  const name = SOURCE_NAME[source];
  const [username, setUsername] = useState("");
  const settings = useSettings().data;
  const [countChoice, setCount] = useState<number | null>(null);
  const count = countChoice ?? settings?.import_count ?? 20;
  const [found, setFound] = useState<PreviewResult | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<ImportResult | null>(null);
  const search = usePreviewGames();
  const commit = useCommitGames();

  const problem = usernameProblem(source, username);
  const canSearch = username.trim().length > 0 && !problem && !search.isPending;
  const isNew = (g: PreviewGame) => g.importable && !g.already_imported;

  const doSearch = () => {
    setResult(null);
    search.mutate(
      { source, username: username.trim(), maxGames: count },
      {
        onSuccess: (r) => {
          setFound(r);
          setPicked(new Set(r.games.filter(isNew).map((g) => g.external_id)));
        },
      },
    );
  };

  const doImport = () => {
    if (!found) return;
    commit.mutate(
      { source, username: found.username, ids: [...picked] },
      {
        onSuccess: (r) => {
          setResult(r);
          const done = new Set([
            ...r.imported.map((g) => g.external_id),
            ...r.duplicates.map((d) => d.game.external_id),
          ]);
          setFound({
            ...found,
            games: found.games.map((g) =>
              done.has(g.external_id) ? { ...g, already_imported: true } : g,
            ),
          });
          setPicked(new Set([...picked].filter((id) => !done.has(id))));
        },
      },
    );
  };

  const toggle = (id: string) =>
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const newGames = found?.games.filter(isNew) ?? [];

  return (
    <div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSearch) doSearch();
        }}
      >
        <label className="min-w-0 flex-1 text-sm">
          <span className="mb-1 block font-medium">{name} username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={!!problem}
            aria-describedby={problem ? `${source}-user-problem` : undefined}
            className={inputCls}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Latest games</span>
          <select
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className={inputCls}
          >
            {[10, 20, 50].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={!canSearch} className={primaryBtn}>
          {search.isPending ? "Searching…" : "Find games"}
        </button>
      </form>
      {problem && (
        <p id={`${source}-user-problem`} className="mt-1 text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
      <p className="mt-1 text-xs text-slate-500">
        Only public games are fetched; no password or login is needed.
      </p>
      <ErrorLine error={search.error ?? commit.error} />

      {found && (
        <div className="mt-3" data-testid="found-games">
          {found.note && (
            <p role="status" className="mb-2 rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">
              {found.note}
            </p>
          )}
          {found.games.length === 0 ? (
            <p className="text-sm text-slate-500">No games found for {found.username}.</p>
          ) : (
            <>
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-slate-500">
                  {found.games.length} game{found.games.length > 1 ? "s" : ""} for {found.username}
                </span>
                <span className="flex gap-2">
                  <button
                    type="button"
                    className="min-h-11 px-1 text-blue-600 underline dark:text-blue-400"
                    onClick={() => setPicked(new Set(newGames.map((g) => g.external_id)))}
                  >
                    Select all new
                  </button>
                  <button
                    type="button"
                    className="min-h-11 px-1 text-blue-600 underline dark:text-blue-400"
                    onClick={() => setPicked(new Set())}
                  >
                    Clear
                  </button>
                </span>
              </div>
              <ul className="max-h-80 divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 px-2 dark:divide-slate-800 dark:border-slate-700">
                {found.games.map((g) => (
                  <GameRow
                    key={g.external_id}
                    game={g}
                    checked={picked.has(g.external_id)}
                    onToggle={() => toggle(g.external_id)}
                  />
                ))}
              </ul>
              <button
                type="button"
                onClick={doImport}
                disabled={picked.size === 0 || commit.isPending}
                className={`${primaryBtn} mt-2`}
              >
                {commit.isPending
                  ? "Importing…"
                  : `Import ${picked.size} selected game${picked.size === 1 ? "" : "s"}`}
              </button>
            </>
          )}
          {result && <ImportResultView result={result} />}
        </div>
      )}
    </div>
  );
}

// ---- a single game link -------------------------------------------------------------------

function LinkImport() {
  const [url, setUrl] = useState("");
  const [hint, setHint] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const navigate = useNavigate();
  const importer = useImportLink();
  const needsUser = /chess\.com/i.test(url);
  const hintProblem = needsUser ? usernameProblem("chesscom", hint) : null;
  const ready = url.trim().length > 0 && !hintProblem && (!needsUser || hint.trim().length > 0);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        importer.mutate(
          { url: url.trim(), usernameHint: needsUser ? hint.trim() : undefined },
          {
            onSuccess: (r) => {
              setResult(r);
              if (r.imported.length + r.duplicates.length === 1 && r.errors.length === 0)
                navigate(`/games/${(r.imported[0] ?? r.duplicates[0].game).id}`);
            },
          },
        );
      }}
    >
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Chess.com or Lichess game link</span>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://lichess.org/abcd1234  or  https://www.chess.com/game/live/…"
          autoComplete="off"
          className={inputCls}
        />
      </label>
      {needsUser && (
        <label className="mt-2 block text-sm">
          <span className="mb-1 block font-medium">Chess.com username of one of the players</span>
          <input
            value={hint}
            onChange={(e) => setHint(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            aria-invalid={!!hintProblem}
            className={inputCls}
          />
          <span className="mt-1 block text-xs text-slate-500">
            Chess.com can't look a game up from its link alone, so we search that player's recent
            games for it.
          </span>
          {hintProblem && <span className="text-xs text-red-600">{hintProblem}</span>}
        </label>
      )}
      <button type="submit" disabled={!ready || importer.isPending} className={`${primaryBtn} mt-2`}>
        {importer.isPending ? "Fetching…" : "Import game"}
      </button>
      <ErrorLine error={importer.error} />
      {result && <ImportResultView result={result} />}
    </form>
  );
}

// ---- the card ------------------------------------------------------------------------------

export function ImportPanel() {
  const [tab, setTab] = useState<Tab>("pgn");
  return (
    <Card title="Import games">
      <div role="tablist" aria-label="Where to import from" className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`import-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="import-panel"
            onClick={() => setTab(t.id)}
            className={`min-h-11 flex-1 border-b-2 px-1 text-sm font-medium ${
              tab === t.id
                ? "border-blue-600 text-blue-700 dark:text-blue-400"
                : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="import-panel" aria-labelledby={`import-tab-${tab}`}>
        {tab === "pgn" && <PgnImport />}
        {tab === "chesscom" && <UsernameImport key="chesscom" source="chesscom" />}
        {tab === "lichess" && <UsernameImport key="lichess" source="lichess" />}
        {tab === "link" && <LinkImport />}
      </div>
    </Card>
  );
}
