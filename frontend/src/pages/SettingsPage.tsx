import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { exportUrl } from "../api/client";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  useDeleteAllGames,
  useDeleteEverything,
  useGames,
  useSettings,
  useUpdateSettings,
} from "../api/hooks";
import type { Settings } from "../api/types";
import { Card } from "../components/Card";

const DEPTH_LABELS: Record<number, string> = {
  10: "Quick",
  14: "Fast",
  16: "Standard",
  18: "Deep",
  20: "Deeper",
  22: "Maximum",
};

const field =
  "rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-950";
const button =
  "inline-flex min-h-11 items-center rounded px-4 text-sm font-semibold disabled:opacity-60";

export const CONFIRM_DELETE_ALL =
  "Delete ALL your saved games and their analyses? This cannot be undone.";
export const CONFIRM_DELETE_EVERYTHING =
  "Delete everything: all games, analyses and settings, and sign this browser out? This cannot be undone.";

function depthOptions(max: number, current: number) {
  const values = new Set([...Object.keys(DEPTH_LABELS).map(Number).filter((d) => d <= max), current]);
  return [...values].sort((a, b) => a - b);
}

function Preferences({ settings }: { settings: Settings }) {
  const save = useUpdateSettings();
  const [depth, setDepth] = useState(settings.default_depth);
  const [lines, setLines] = useState(settings.default_multipv);
  const [count, setCount] = useState(settings.import_count);
  const [auto, setAuto] = useState(!!settings.auto_analyze);
  const [ai, setAi] = useState(!!settings.ai_explanations);
  const [level, setLevel] = useState(settings.explain_level ?? "intermediate");
  const [names, setNames] = useState((settings.my_names ?? []).join(", "));
  const parsedNames = names.split(",").map((n) => n.trim()).filter(Boolean);
  const dirty =
    depth !== settings.default_depth ||
    lines !== settings.default_multipv ||
    count !== settings.import_count ||
    auto !== !!settings.auto_analyze ||
    ai !== !!settings.ai_explanations ||
    level !== (settings.explain_level ?? "intermediate") ||
    parsedNames.join("|") !== (settings.my_names ?? []).join("|");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ default_depth: depth, default_multipv: lines, import_count: count, auto_analyze: auto, my_names: parsedNames, ai_explanations: ai, explain_level: level });
      }}
      className="space-y-4"
    >
      <fieldset className="grid gap-3 sm:grid-cols-3">
        <legend className="mb-1 text-sm font-semibold">Analysis defaults</legend>
        <label className="text-sm">
          <span className="mb-1 block">Search depth</span>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className={`${field} w-full`}
          >
            {depthOptions(settings.max_depth, settings.default_depth).map((d) => (
              <option key={d} value={d}>
                {DEPTH_LABELS[d] ? `${DEPTH_LABELS[d]} (depth ${d})` : `Depth ${d}`}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block">Engine lines</span>
          <select
            value={lines}
            onChange={(e) => setLines(Number(e.target.value))}
            className={`${field} w-full`}
          >
            {Array.from({ length: settings.max_multipv }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n === 1 ? "1 line (fastest)" : `${n} lines`}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-600 dark:text-slate-400 sm:col-span-3">
          Used when you press "Analyze game". You can still choose differently for a single game.
          Deeper searches and more lines are more informative but take longer.
        </p>
      </fieldset>

<fieldset className="space-y-2">        <legend className="mb-1 text-sm font-semibold">Who you are</legend>        <label className="block text-sm">          <span className="mb-1 block">Your player names</span>          <input            value={names}            onChange={(e) => setNames(e.target.value)}            placeholder="e.g. DrNykterstein, Magnus"            autoComplete="off"            autoCapitalize="none"            spellCheck={false}            className={`${field} w-full`}          />        </label>        <p className="text-xs text-slate-600 dark:text-slate-400">          Separate several with commas (up to 5). The Train and Stats pages use them to tell which side of a game was          you; remembered Chess.com / Lichess accounts count too. A game where neither side (or both) matches is left out.        </p>      </fieldset>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-semibold">AI explanations</legend>
        {!settings.ai_available ? (
          <p className="text-sm text-slate-600 dark:text-slate-400" data-testid="ai-unavailable">
            AI explanations are not set up on this server.
          </p>
        ) : (
          <>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} className="mt-1" />
              <span>
                Explain moves with AI
                <span className="block text-xs text-slate-600 dark:text-slate-400" data-testid="ai-notice">
When you ask for an explanation, the position, the move and the engine's lines (never names or                  whole games) are sent to {settings.ai_provider ?? "the model provider"}. Check their data terms: free models                  may use what they receive to improve themselves.
                  The text is written by an AI and checked against the engine's analysis, but it can still be wrong; the
                  engine's lines are the facts. Off by default. You can ask for up to {settings.explain_daily_limit ?? 0} a day.
                </span>
              </span>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block">Explain at the level of a</span>
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as typeof level)}
                disabled={!ai}
                className={`${field} w-full sm:w-48`}
              >
                <option value="beginner">beginner</option>
                <option value="intermediate">intermediate</option>
                <option value="advanced">advanced</option>
              </select>
            </label>
          </>
        )}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-semibold">New games</legend>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
            className="mt-1"
          />
          <span>
            Analyze new games automatically after importing them
            <span className="block text-xs text-slate-600 dark:text-slate-400">
              Uses the depth and lines above, up to 20 games per import, one after another so it never
              blocks you from analyzing a single game. Off by default; it uses the server's processor.
            </span>
          </span>
        </label>
      </fieldset>

      <fieldset className="grid gap-3 sm:grid-cols-3">
        <legend className="mb-1 text-sm font-semibold">Import preferences</legend>
        <label className="text-sm">
          <span className="mb-1 block">Games per Chess.com / Lichess search</span>
          <select
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className={`${field} w-full`}
          >
            {[10, 20, 50].map((n) => (
              <option key={n} value={n}>
                {n} games
              </option>
            ))}
          </select>
        </label>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={!dirty || save.isPending}
          className={`${button} bg-blue-600 text-white hover:bg-blue-700`}
        >
          {save.isPending ? "Saving…" : "Save settings"}
        </button>
        {save.isSuccess && !dirty && (
          <span role="status" className="text-sm text-green-700 dark:text-green-400">
            Saved.
          </span>
        )}
        {save.isError && (
          <span role="alert" className="text-sm text-red-600">
            {(save.error as Error).message}
          </span>
        )}
      </div>
    </form>
  );
}

function Privacy({ settings }: { settings: Settings | undefined }) {
  const navigate = useNavigate();
  const games = useGames(1, 1);
  const delAll = useDeleteAllGames();
  const delEverything = useDeleteEverything();
  const total = games.data?.total ?? 0;
  const days = settings?.retention_days ?? 0;

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Your games belong to this browser's anonymous session; there is no account.{" "}
        {days > 0
          ? `If you don't visit for ${days} days, your games and analyses are deleted automatically.`
          : "Your data is kept until you delete it."}
      </p>

      <div>
        <h3 className="mb-1 text-sm font-semibold">Export</h3>
        {total > 0 ? (
          <a
            href={exportUrl({})}
            download
            className={`${button} border border-slate-300 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800`}
          >
            Download all {total} game{total === 1 ? "" : "s"} (PGN)
          </a>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-400">No games to export yet.</p>
        )}
        <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          Keep a copy: if you clear your browser data you will lose access to your games here. A
          PGN file can be imported again at any time.
        </p>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold">Delete</h3>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={total === 0 || delAll.isPending}
            onClick={() => window.confirm(CONFIRM_DELETE_ALL) && delAll.mutate()}
            className={`${button} border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950`}
          >
            Delete all my games
          </button>
          <button
            type="button"
            disabled={delEverything.isPending}
            onClick={() =>
              window.confirm(CONFIRM_DELETE_EVERYTHING) &&
              delEverything.mutate(undefined, { onSuccess: () => navigate("/") })
            }
            className={`${button} bg-red-600 text-white hover:bg-red-700`}
          >
            Delete everything and start over
          </button>
        </div>
        {delAll.isSuccess && (
          <p role="status" className="mt-2 text-sm text-green-700 dark:text-green-400">
            Deleted {delAll.data.deleted} game{delAll.data.deleted === 1 ? "" : "s"}.
          </p>
        )}
        {(delAll.isError || delEverything.isError) && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {((delAll.error ?? delEverything.error) as Error).message}
          </p>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  useDocumentTitle("Settings");
  const settings = useSettings();
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-4">
      <h1 className="text-xl font-bold">Settings</h1>
      <Card title="Preferences">
        {settings.isLoading && <p role="status" className="text-sm text-slate-600 dark:text-slate-400">Loading…</p>}
        {settings.isError && (
          <p role="alert" className="text-sm text-red-600">
            Could not load your settings: {(settings.error as Error).message}
          </p>
        )}
        {settings.data && <Preferences settings={settings.data} />}
      </Card>
      <Card title="Privacy and data">
        <Privacy settings={settings.data} />
      </Card>
    </div>
  );
}
