import { useState } from "react";
import { useBatchEstimate, useCancelBatch, useLatestBatch, useSettings, useStartBatch } from "../api/hooks";
import type { Batch, BatchRequest, GameQuery } from "../api/types";
import { durationText } from "../lib/format";
import { Card } from "./Card";

/** The history filters, as the batch endpoint wants them. */
export function batchRequestFor(query: GameQuery): BatchRequest {
  const filter: NonNullable<BatchRequest["filter"]> = {};
  if (query.q?.trim()) filter.q = query.q.trim();
  if (query.source) filter.source = query.source;
  if (query.result) filter.result = query.result;
  if (query.from) filter.date_from = query.from;
  if (query.to) filter.date_to = query.to;
  if (query.favorite) filter.favorite = true;
  if (query.tag?.trim()) filter.tag = query.tag.trim();
  return { filter, only_unanalyzed: true };
}

const btn =
  "min-h-11 rounded px-3 py-2 text-sm font-semibold";

function summaryText(b: Batch): string {
  const c = b.counts;
  const parts = [`${c.done} analyzed`];
  if (c.failed) parts.push(`${c.failed} failed`);
  if (c.skipped) parts.push(`${c.skipped} skipped`);
  if (c.cancelled) parts.push(`${c.cancelled} cancelled`);
  return parts.join(", ");
}

function Running({ batch }: { batch: Batch }) {
  const cancel = useCancelBatch();
  const c = batch.counts;
  const counted = batch.total - c.skipped; // skipped games never run
  const finished = c.done + c.failed + c.cancelled;
  const pct = counted ? Math.round((finished / counted) * 100) : 100;
  const current = batch.items.find((i) => i.state === "queued" && i.progress_total);
  return (
    <section aria-label="Analyze all" className="space-y-2" aria-live="polite" data-testid="batch-running">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">
          Analyzing your games: {finished} of {counted} done
        </span>
        <button
          type="button"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(batch.id)}
          className={`${btn} border border-slate-300 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800`}
        >
          Cancel
        </button>
      </div>
      <div
        role="progressbar"
        aria-label="Games analyzed"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-800"
      >
        <div className="h-full bg-blue-600 transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        {current
          ? `Now: ${current.white} vs ${current.black} (${current.progress_done}/${current.progress_total} positions). `
          : ""}
        {c.failed > 0 && `${c.failed} failed so far. `}
        You can keep using the app; cancelling stops after the current position and keeps existing reviews.
      </p>
    </section>
  );
}

function Finished({ batch, onDismiss }: { batch: Batch; onDismiss: () => void }) {
  const problems = batch.items.filter((i) => i.state === "failed" || i.state === "skipped");
  return (
    <section aria-label="Last batch" className="space-y-1 text-sm" data-testid="batch-finished">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p>
          <span className="font-semibold">{batch.status === "cancelled" ? "Batch cancelled" : "Batch finished"}:</span>{" "}
          {summaryText(batch)}.
        </p>
        <button type="button" onClick={onDismiss} className="min-h-11 px-2 text-blue-600 underline dark:text-blue-400">
          Dismiss
        </button>
      </div>
      {problems.length > 0 && (
        <ul className="list-inside list-disc text-xs text-slate-600 dark:text-slate-400">
          {problems.map((i) => (
            <li key={i.game_id}>
              {i.white} vs {i.black}: {i.state === "skipped" ? "skipped" : "failed"}
              {i.message ? ` (${i.message})` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** "Analyze all" for the games matching the current filters that have no review yet. */
export function BatchPanel({ query }: { query: GameQuery }) {
  const latest = useLatestBatch();
  const settings = useSettings().data;
  const start = useStartBatch();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const request = batchRequestFor(query);
  const batch = latest.data;
  const running = batch?.status === "running";
  const estimate = useBatchEstimate(request, !running && !latest.isLoading);

  if (running && batch) {
    return (
      <Card className="mb-4">
        <Running batch={batch} />
      </Card>
    );
  }

  const e = estimate.data;
  const showFinished = batch && batch.id !== dismissed;
  if (!showFinished && (!e || e.games === 0)) return null;

  return (
    <Card className="mb-4">
      {showFinished && <Finished batch={batch} onDismiss={() => setDismissed(batch.id)} />}
      {e && e.games > 0 && (
        <div className={`flex flex-wrap items-center justify-between gap-2 ${showFinished ? "mt-3 border-t border-slate-200 pt-3 dark:border-slate-800" : ""}`}>
          <p className="text-sm text-slate-600 dark:text-slate-400" data-testid="batch-estimate">
            {e.too_many ? (
              <>Too many games to analyze at once (the limit is {e.max_games}). Narrow the filters.</>
            ) : (
              <>
                {e.games} game{e.games === 1 ? "" : "s"} without a review
                {e.seconds != null && e.seconds_high != null && (
                  <>
                    : about {durationText(e.seconds).replace("about ", "")}, possibly up to{" "}
                    {durationText(e.seconds_high).replace("about ", "")} in total
                  </>
                )}
                {settings && ` (depth ${settings.default_depth}, ${settings.default_multipv} lines)`}.
                {e.skipped > 0 && ` ${e.skipped} cannot be analyzed with these settings.`}
              </>
            )}
          </p>
          <button
            type="button"
            disabled={start.isPending || e.too_many}
            onClick={() => start.mutate(request)}
            className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}
          >
            {start.isPending ? "Starting…" : `Analyze ${e.games} game${e.games === 1 ? "" : "s"}`}
          </button>
        </div>
      )}
      {start.error && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {(start.error as Error).message}
        </p>
      )}
    </Card>
  );
}
