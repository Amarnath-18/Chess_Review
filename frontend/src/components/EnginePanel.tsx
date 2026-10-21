import type { EngineLine, PositionAnalysis } from "../api/types";
import { evalText } from "../lib/format";
import { CLASS_META, LINE_DOT_CLASSES } from "../lib/quality";
import { ClassBadge } from "./ClassBadge";

interface Props {
  /** Analysis of the position on the board (ply k) and of the one before it (ply k-1). */
  current: PositionAnalysis;
  previous: PositionAnalysis | null;
  onExplore: (basePly: number, sans: string[], upTo: number) => void;
  /** How many engine lines to display, and how many the analysis contains. */
  shown: number;
  maxLines: number;
  onShownChange: (n: number) => void;
}

function MoveChips({
  basePly,
  sans,
  label,
  onExplore,
}: {
  basePly: number;
  sans: string[];
  label: string;
  onExplore: Props["onExplore"];
}) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
      {sans.map((san, i) => (
        <button
          key={i}
          type="button"
          title="Play this line on the board (not saved)"
          onClick={() => onExplore(basePly, sans, i + 1)}
          className="rounded bg-slate-200 px-1.5 py-0.5 text-sm hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-700"
        >
          {san}
        </button>
      ))}
    </div>
  );
}

function LinesControl({ shown, max, onChange }: { shown: number; max: number; onChange: (n: number) => void }) {
  if (max <= 1) return null;
  return (
    <div className="flex items-center gap-1 text-xs text-slate-500" role="group" aria-label="Engine lines shown">
      <span>Lines</span>
      {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
        <button
          key={n}
          type="button"
          aria-pressed={shown === n}
          onClick={() => onChange(n)}
          className={`h-7 w-7 rounded border text-sm font-medium ${
            shown === n
              ? "border-blue-600 bg-blue-600 text-white"
              : "border-slate-300 bg-white hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:hover:bg-slate-700"
          }`}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

export function EnginePanel({ current, previous, onExplore, shown, maxLines, onShownChange }: Props) {
  const played = current.played_move_san;
  const cls = current.classification;
  const meta = cls ? CLASS_META[cls] : null;
  const prefersOther =
    previous?.best_move_san &&
    previous.best_move_uci !== current.played_move_uci &&
    (cls === null || (cls !== "best" && cls !== "great" && cls !== "brilliant"));

  const lines: EngineLine[] = current.lines.slice(0, Math.max(1, shown));

  return (
    <section aria-label="Engine analysis" className="space-y-3" data-testid="engine-panel">
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-2xl font-bold tabular-nums" data-testid="engine-eval">
            {evalText(current.eval)}
          </span>
          <span className="ml-2 text-xs text-slate-500">White's perspective</span>
        </div>
        {current.depth !== null && <span className="text-xs text-slate-500">depth {current.depth}</span>}
      </div>

      {played && (
        <div className="rounded border border-slate-200 p-2 dark:border-slate-700" data-testid="played-move">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">Played {played}</span>
            {cls && <ClassBadge cls={cls} />}
            {current.missed_win && (
              <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-900 dark:text-red-100">
                Miss: a win was available
              </span>
            )}
            {current.is_sacrifice && (
              <span className="rounded bg-teal-100 px-1.5 py-0.5 text-xs font-semibold text-teal-800 dark:bg-teal-900 dark:text-teal-100">
                Sacrifice
              </span>
            )}
          </div>
          {meta && <p className="mt-1 text-xs text-slate-500">{meta.blurb}.</p>}
          {current.loss_pct !== null && current.loss_pct > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              Cost {current.loss_pct.toFixed(1)} points of winning chances compared with the
              engine's first choice.
            </p>
          )}
          {prefersOther && previous && (
            <div className="mt-2 space-y-1">
              <div className="text-xs text-slate-500">
                Engine preferred {previous.best_move_san} ({evalText(previous.eval)})
              </div>
              <MoveChips
                basePly={previous.ply}
                sans={previous.pv_san}
                label={`Engine preferred ${previous.best_move_san}`}
                onExplore={onExplore}
              />
            </div>
          )}
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Engine lines</h3>
          <LinesControl shown={shown} max={Math.min(maxLines, 5)} onChange={onShownChange} />
        </div>
        {lines.length === 0 && (
          <p className="text-sm text-slate-500">
            {current.eval.terminal_result ? `Game over: ${current.eval.terminal_result}` : "No engine lines for this position."}
          </p>
        )}
        <ol className="space-y-2" data-testid="engine-lines">
          {lines.map((ln) => (
            <li key={ln.rank} className="flex items-start gap-2" data-testid={`engine-line-${ln.rank}`}>
              <span
                className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${LINE_DOT_CLASSES[ln.rank - 1] ?? "bg-slate-500"}`}
                aria-hidden="true"
              />
              <span className="mt-0.5 w-14 shrink-0 text-right text-sm font-semibold tabular-nums">
                {evalText(ln.eval)}
              </span>
              <MoveChips
                basePly={current.ply}
                sans={ln.pv_san}
                label={`Line ${ln.rank}: ${ln.move_san ?? ""}`}
                onExplore={onExplore}
              />
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
