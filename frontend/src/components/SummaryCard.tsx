import type { ReviewSummary } from "../api/types";
import { CLASS_META, CLASS_ORDER, reasonLabel } from "../lib/quality";

interface Props {
  summary: ReviewSummary;
  white: string;
  black: string;
  onSelectPly: (ply: number) => void;
  moveLabel: (ply: number) => string;
}

function formatAccuracy(value: number | null): string {
  return value === null ? "–" : `${value.toFixed(1)}%`;
}

export function SummaryCard({ summary, white, black, onSelectPly, moveLabel }: Props) {
  return (
    <section aria-label="Review summary" className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold ${
            summary.complete
              ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100"
              : "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100"
          }`}
        >
          {summary.complete ? "Analysis complete" : "Analysis incomplete"}
        </span>
        <span className="text-slate-600 dark:text-slate-400">
          {summary.analyzed_moves} of {summary.total_moves} moves evaluated
        </span>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-600 dark:text-slate-400">
            <th scope="col" className="py-1 font-medium">Move quality</th>
            <th scope="col" className="w-20 py-1 text-right font-medium">{white}</th>
            <th scope="col" className="w-20 py-1 text-right font-medium">{black}</th>
          </tr>
        </thead>
        <tbody>
          {summary.accuracy && (
            <tr className="border-t border-slate-200 dark:border-slate-800">
              <th scope="row" className="py-1 text-left font-semibold">Accuracy</th>
              <td className="py-1 text-right font-semibold tabular-nums" data-testid="accuracy-white">
                {formatAccuracy(summary.accuracy.white)}
              </td>
              <td className="py-1 text-right font-semibold tabular-nums" data-testid="accuracy-black">
                {formatAccuracy(summary.accuracy.black)}
              </td>
            </tr>
          )}
          {CLASS_ORDER.map((c) => {
            const meta = CLASS_META[c];
            const w = summary.counts.white[c];
            const b = summary.counts.black[c];
            return (
              <tr key={c} className="border-t border-slate-200 dark:border-slate-800">
                <th scope="row" className="py-1 text-left font-normal">
                  <span className="inline-flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} aria-hidden="true" />
                    {meta.label}
                    {meta.glyph && <span className={`text-xs font-bold ${meta.text}`} aria-hidden="true">{meta.glyph}</span>}
                  </span>
                </th>
                <td className="py-1 text-right tabular-nums" data-testid={`count-white-${c}`}>{w}</td>
                <td className="py-1 text-right tabular-nums" data-testid={`count-black-${c}`}>{b}</td>
              </tr>
            );
          })}
          <tr className="border-t border-slate-200 dark:border-slate-800">
            <th scope="row" className="py-1 text-left font-normal">Missed wins</th>
            <td className="py-1 text-right tabular-nums">{summary.missed_wins.white}</td>
            <td className="py-1 text-right tabular-nums">{summary.missed_wins.black}</td>
          </tr>
        </tbody>
      </table>

      {summary.key_positions.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Key positions to review</h3>
          <ul className="space-y-1">
            {summary.key_positions.map((k) => (
              <li key={k.ply}>
                <button
                  type="button"
                  onClick={() => onSelectPly(k.ply)}
                  className="flex w-full items-baseline justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-200 dark:hover:bg-slate-800"
                >
                  <span className="font-medium">{moveLabel(k.ply)}</span>
                  <span className="text-xs text-slate-600 dark:text-slate-400">{k.reasons.map(reasonLabel).join(" · ")}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-slate-600 dark:text-slate-400">
        Accuracy uses the Lichess-style method on this analysis (higher is better). It is this
        app's own number and will not match Chess.com's.
      </p>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        Labels compare each move with Stockfish's evaluation at the chosen search depth. They are
        guidance for study, not verdicts: a move can differ from the engine's first choice and still
        be perfectly reasonable.
      </p>
    </section>
  );
}
