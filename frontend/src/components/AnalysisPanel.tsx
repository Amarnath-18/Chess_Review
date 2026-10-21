import { useState } from "react";
import { ApiError } from "../api/client";
import { useRetryJob, useStartAnalysis } from "../api/hooks";
import type { Analysis, GameDetail, Job } from "../api/types";

const DEPTHS = [
  { v: 10, label: "Quick (depth 10)" },
  { v: 14, label: "Fast (depth 14)" },
  { v: 16, label: "Standard (depth 16)" },
  { v: 18, label: "Deep (depth 18)" },
  { v: 20, label: "Deeper (depth 20)" },
  { v: 22, label: "Maximum (depth 22)" },
];

// More lines cost more search time. Two or more are needed for the Great / Brilliant labels.
const LINE_OPTIONS = [1, 2, 3, 4, 5];

interface Props {
  game: GameDetail;
  job: Job | null;
  analysis: Analysis | undefined;
}

export function AnalysisPanel({ game, job, analysis }: Props) {
  const [depth, setDepth] = useState(analysis?.run.depth ?? 16);
  const [lines, setLines] = useState(analysis?.run.multipv ?? 3);
  const [open, setOpen] = useState(false);
  const start = useStartAnalysis(game.id);
  const retry = useRetryJob(game.id);

  const active = job && (job.status === "queued" || job.status === "running");
  const failed = job?.status === "failed";
  const error = (start.error ?? retry.error) as Error | null;
  const busy = start.isPending || retry.isPending;

  if (active) {
    const pct = job.progress_total ? Math.round((job.progress_done / job.progress_total) * 100) : 0;
    return (
      <section aria-label="Analysis status" className="space-y-2" aria-live="polite">
        <div className="flex justify-between text-sm">
          <span className="font-medium">
            {job.status === "queued" ? "Waiting for the engine…" : "Analyzing…"}
          </span>
          <span className="tabular-nums text-slate-500">
            {job.progress_done}/{job.progress_total} positions
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          className="h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-800"
        >
          <div className="h-full bg-blue-600 transition-[width] duration-300" style={{ width: `${pct}%` }} />
        </div>
        {analysis && (
          <p className="text-xs text-slate-500">The previous review stays available until this finishes.</p>
        )}
      </section>
    );
  }

  const form = (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        start.mutate({ depth, multipv: lines });
        setOpen(false);
      }}
    >
      <label className="text-sm">
        <span className="mb-1 block text-xs text-slate-500">Search depth</span>
        <select
          value={depth}
          onChange={(e) => setDepth(Number(e.target.value))}
          className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
        >
          {DEPTHS.map((d) => (
            <option key={d.v} value={d.v}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block text-xs text-slate-500">Engine lines</span>
        <select
          value={lines}
          onChange={(e) => setLines(Number(e.target.value))}
          className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
        >
          {LINE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n === 1 ? "1 line (fastest)" : `${n} lines`}
            </option>
          ))}
        </select>
      </label>
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
      >
        {analysis ? "Re-analyze" : "Analyze game"}
      </button>
    </form>
  );

  return (
    <section aria-label="Analysis" className="space-y-2">
      {failed && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <p className="font-semibold">The last analysis did not finish.</p>
          <p>{job?.error ?? "Unknown error."}</p>
          {analysis && <p className="mt-1">Your earlier review is unchanged.</p>}
          <button
            type="button"
            disabled={busy}
            onClick={() => job && retry.mutate(job.id)}
            className="mt-2 rounded bg-red-600 px-3 py-1 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error instanceof ApiError ? error.message : "Something went wrong."}
        </p>
      )}

      {analysis ? (
        <div className="text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-slate-500">
              {analysis.run.engine_name} · depth {analysis.run.depth ?? `${analysis.run.nodes} nodes`}
              {` · ${analysis.run.multipv} line${analysis.run.multipv > 1 ? "s" : ""}`}
            </span>
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              className="text-blue-600 underline hover:no-underline dark:text-blue-400"
            >
              {open ? "Cancel" : "Different settings…"}
            </button>
          </div>
          {open && <div className="mt-2">{form}</div>}
        </div>
      ) : (
        <div>
          <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">
            This game has not been analyzed yet. Stockfish will evaluate every position; deeper
            searches and more lines are more informative but take longer.
          </p>
          {form}
        </div>
      )}
      {start.data?.cached && (
        <p className="text-xs text-slate-500">A review with these settings already existed, so it was reused.</p>
      )}
    </section>
  );
}
