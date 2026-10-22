import { useState } from "react";
import { useCheckSource, useCommitGames, useForgetSource, useSources } from "../api/hooks";
import type { ImportResult, LinkedSource, NewGames } from "../api/types";
import { dateText, playerLabel } from "../lib/format";
import { Card } from "./Card";
import { ImportResultView } from "./ImportPanel";

const SOURCE_NAME = { chesscom: "Chess.com", lichess: "Lichess" } as const;
const btn =
  "min-h-11 rounded border border-slate-300 px-3 text-sm font-medium hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800";

function lastChecked(s: LinkedSource): string {
  return s.last_checked_at ? `last checked ${dateText(s.last_checked_at.slice(0, 10))}` : "not checked yet";
}

function Account({ source }: { source: LinkedSource }) {
  const check = useCheckSource();
  const commit = useCommitGames();
  const forget = useForgetSource();
  const [found, setFound] = useState<NewGames | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const error = (check.error ?? commit.error ?? forget.error) as Error | null;

  const doCheck = () => {
    setResult(null);
    check.mutate(source.id, { onSuccess: setFound });
  };
  const doImport = () => {
    if (!found) return;
    commit.mutate(
      { source: source.source, username: source.username, ids: found.new_games.map((g) => g.external_id) },
      {
        onSuccess: (r) => {
          setResult(r);
          setFound({ ...found, new_games: [] });
        },
      },
    );
  };

  return (
    <li className="py-2" data-testid="saved-account">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{source.username}</div>
          <div className="text-xs text-slate-600 dark:text-slate-400">
            {SOURCE_NAME[source.source]} · {lastChecked(source)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={doCheck} disabled={check.isPending} className={btn}>
            {check.isPending ? "Checking…" : "Check for new games"}
          </button>
          <button
            type="button"
            aria-label={`Forget ${source.username} on ${SOURCE_NAME[source.source]}`}
            onClick={() => forget.mutate(source.id)}
            disabled={forget.isPending}
            className={`${btn} hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-950`}
          >
            Forget
          </button>
        </div>
      </div>

      {found && (
        <div className="mt-2 text-sm" aria-live="polite" data-testid="check-result">
          {found.new_games.length === 0 && !result ? (
            <p className="text-slate-600 dark:text-slate-400">
              No new games among the latest {found.checked}
              {found.cannot_import > 0 ? ` (${found.cannot_import} new but not importable, e.g. variants)` : ""}.
            </p>
          ) : found.new_games.length > 0 ? (
            <>
              <p className="font-medium">
                {found.new_games.length} new game{found.new_games.length === 1 ? "" : "s"}:
              </p>
              <ul className="my-1 max-h-48 list-inside list-disc overflow-y-auto text-xs text-slate-600 dark:text-slate-400">
                {found.new_games.map((g) => (
                  <li key={g.external_id}>
                    {playerLabel(g.white, g.white_elo)} vs {playerLabel(g.black, g.black_elo)} · {dateText(g.played_at)}
                  </li>
                ))}
              </ul>
              <button
                type="button"
                onClick={doImport}
                disabled={commit.isPending}
                className="min-h-11 rounded bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700"
              >
                {commit.isPending ? "Importing…" : `Import ${found.new_games.length} new game${found.new_games.length === 1 ? "" : "s"}`}
              </button>
              {found.checked >= 50 && (
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                  Only the latest {found.checked} games are looked at, so if you played more than that since
                  your last check, older ones may be missing.
                </p>
              )}
            </>
          ) : null}
          {result && <ImportResultView result={result} />}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
          {error.message}
        </p>
      )}
    </li>
  );
}

/** Remembered Chess.com / Lichess accounts, each with a "check for new games" button. */
export function SavedAccounts() {
  const sources = useSources();
  if (!sources.data || sources.data.length === 0) return null;
  return (
    <Card title="Your accounts">
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {sources.data.map((s) => (
          <Account key={s.id} source={s} />
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
        Only the public username is remembered, never a password. Checking looks at your latest games on
        request; nothing is fetched in the background.
      </p>
    </Card>
  );
}
