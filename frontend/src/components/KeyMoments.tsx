import { useState } from "react";
import { useExplain, useExplanations } from "../api/hooks";
import { ExplanationNote, useAiReady } from "./ExplainBox";

const MAX_MOMENTS = 8;

/** "Explain key moments": the review's most important positions, explained one after another. */
export function KeyMoments({
  gameId,
  plies,
  moveLabel,
  onSelectPly,
}: {
  gameId: string;
  plies: number[];
  moveLabel: (ply: number) => string;
  onSelectPly: (ply: number) => void;
}) {
  const ai = useAiReady();
  const list = useExplanations(gameId, ai.on);
  const explain = useExplain(gameId);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (!ai.on || plies.length === 0) return null;

  const chosen = plies.slice(0, MAX_MOMENTS);
  const have = new Map((list.data?.items ?? []).map((i) => [i.ply, i]));
  const missing = chosen.filter((p) => !have.has(p));

  const run = async () => {
    setProblem(null);
    let done = 0;
    setProgress({ done, total: missing.length });
    for (const ply of missing) {
      try {
        await explain.mutateAsync(ply);
      } catch (e) {
        setProblem((e as Error).message); // a limit or an outage: stop, keep what we have
        break;
      }
      done += 1;
      setProgress({ done, total: missing.length });
    }
    setProgress(null);
  };

  return (
    <div className="space-y-2" data-testid="key-moments">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">AI explanations of key moments</h3>
        {missing.length > 0 && (
          <button
            type="button"
            onClick={run}
            disabled={!!progress}
            className="min-h-11 rounded border border-blue-600 px-3 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-400 dark:text-blue-300 dark:hover:bg-blue-950"
          >
            {progress ? `Explaining ${progress.done + 1} of ${progress.total}…` : `Explain ${missing.length} key moment${missing.length === 1 ? "" : "s"}`}
          </button>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-xs text-red-700 dark:text-red-300">
          {problem}
        </p>
      )}
      <ul className="space-y-2">
        {chosen
          .filter((p) => have.has(p))
          .map((p) => {
            const e = have.get(p)!;
            return (
              <li key={p} className="rounded border border-slate-200 p-2 text-sm dark:border-slate-700">
                <button
                  type="button"
                  onClick={() => onSelectPly(p)}
                  className="font-medium text-blue-700 underline dark:text-blue-300"
                >
                  {moveLabel(p)}
                </button>
                <p className="mt-1">{e.text}</p>
                <ExplanationNote source={e.source} />
              </li>
            );
          })}
      </ul>
    </div>
  );
}
