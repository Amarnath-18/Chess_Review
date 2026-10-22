import { useState } from "react";
import type { ClockInfo, MoveClass } from "../api/types";
import { clockSeries, formatClock, longestThink, sideTimes } from "../lib/clocks";
import { plyAtX } from "../lib/graph";

interface Props {
  clocks: ClockInfo[];
  startFen: string;
  classes: (MoveClass | null)[] | undefined;
  white: string;
  black: string;
  currentPly: number;
  onSelect: (ply: number) => void;
  moveLabel: (ply: number) => string;
}

const W = 600;
const H = 120;

const pathOf = (run: { x: number; y: number }[]) =>
  run.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

/** Remaining time for both sides over the game, plus what the clocks say about the mistakes. */
export function ClockPanel({ clocks, startFen, classes, white, black, currentPly, onSelect, moveLabel }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const total = clocks.length;
  const maxSeconds = Math.max(1, ...clocks.map((c) => c.clock ?? 0));
  const shown = hover ?? currentPly;
  const info = clocks.find((c) => c.ply === shown);

  const sides = [
    { key: "white" as const, name: white, isWhite: true, stroke: "stroke-white", swatch: "bg-white border border-slate-400" },
    { key: "black" as const, name: black, isWhite: false, stroke: "stroke-amber-400", swatch: "bg-amber-400" },
  ];

  const sentences: string[] = [];
  for (const s of sides) {
    const t = sideTimes(clocks, classes, startFen, s.isWhite);
    if (t.errors > 0 && classes) {
      sentences.push(
        t.errorsInTrouble > 0
          ? `${t.errorsInTrouble} of ${s.name}'s ${t.errors} mistake${t.errors > 1 ? "s" : ""} or blunder${t.errors > 1 ? "s" : ""} came in time trouble.`
          : `None of ${s.name}'s ${t.errors} mistake${t.errors > 1 ? "s" : ""} or blunder${t.errors > 1 ? "s" : ""} came in time trouble.`,
      );
    }
  }

  return (
    <section aria-label="Clock times" className="space-y-3" data-testid="clock-panel">
      <figure className="m-0">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-400">
          <span className="flex items-center gap-3">
            {sides.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1">
                <span className={`h-2.5 w-2.5 rounded-full ${s.swatch}`} aria-hidden="true" />
                {s.name}
              </span>
            ))}
          </span>
          <span data-testid="clock-readout">
            {shown === 0
              ? "Start"
              : `${moveLabel(shown)} · ${formatClock(info?.clock)} left${info?.spent != null ? ` · took ${formatClock(info.spent)}` : ""}`}
          </span>
        </div>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full cursor-pointer touch-none rounded border border-slate-300 bg-slate-700 dark:border-slate-600"
          role="img"
          aria-label={`Clock graph: time remaining for each side over ${total} moves. Click to select a move.`}
          data-testid="clock-graph"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            onSelect(plyAtX(e.clientX - rect.left, rect.width, total));
          }}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setHover(plyAtX(e.clientX - rect.left, rect.width, total));
          }}
          onPointerLeave={() => setHover(null)}
        >
          {sides.map((s) =>
            clockSeries(clocks, startFen, s.isWhite, W, H, maxSeconds).map((run, i) =>
              run.length > 1 ? (
                <path key={`${s.key}${i}`} d={pathOf(run)} className={`fill-none ${s.stroke}`} strokeWidth={2} />
              ) : (
                <circle key={`${s.key}${i}`} cx={run[0].x} cy={run[0].y} r={2.5} className={s.isWhite ? "fill-white" : "fill-amber-400"} />
              ),
            ),
          )}
          {clocks
            .filter((c) => c.time_trouble)
            .map((c) => (
              <line
                key={c.ply}
                x1={(c.ply / Math.max(1, total)) * W}
                x2={(c.ply / Math.max(1, total)) * W}
                y1={H - 8}
                y2={H}
                className="stroke-red-500"
                strokeWidth={3}
              >
                <title>{`Time trouble at ${moveLabel(c.ply)}`}</title>
              </line>
            ))}
          {currentPly > 0 && (
            <line
              x1={(currentPly / Math.max(1, total)) * W}
              x2={(currentPly / Math.max(1, total)) * W}
              y1={0}
              y2={H}
              className="stroke-blue-400"
              strokeWidth={2}
            />
          )}
        </svg>
        <figcaption className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          Time left on each clock (top = most). Red ticks mark moves played in time trouble.
        </figcaption>
      </figure>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-600 dark:text-slate-400">
            <th scope="col" className="py-1 font-medium">Time</th>
            <th scope="col" className="w-24 py-1 text-right font-medium">{white}</th>
            <th scope="col" className="w-24 py-1 text-right font-medium">{black}</th>
          </tr>
        </thead>
        <tbody>
          {(() => {
            const [w, b] = sides.map((s) => sideTimes(clocks, classes, startFen, s.isWhite));
            const [lw, lb] = sides.map((s) => longestThink(clocks, startFen, s.isWhite));
            const avg = (t: typeof w) => (t.timedMoves ? formatClock(t.totalSpent / t.timedMoves) : "–");
            return (
              <>
                <tr className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="py-1 text-left font-normal">Average per move</th>
                  <td className="py-1 text-right tabular-nums" data-testid="avg-white">{avg(w)}</td>
                  <td className="py-1 text-right tabular-nums" data-testid="avg-black">{avg(b)}</td>
                </tr>
                <tr className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="py-1 text-left font-normal">Longest think</th>
                  {[lw, lb].map((l, i) => (
                    <td key={i} className="py-1 text-right tabular-nums">
                      {l ? (
                        <button
                          type="button"
                          onClick={() => onSelect(l.ply)}
                          className="min-h-8 rounded px-1 text-blue-700 underline dark:text-blue-400"
                        >
                          {formatClock(l.spent)}
                        </button>
                      ) : (
                        "–"
                      )}
                    </td>
                  ))}
                </tr>
                <tr className="border-t border-slate-200 dark:border-slate-800">
                  <th scope="row" className="py-1 text-left font-normal">Moves in time trouble</th>
                  <td className="py-1 text-right tabular-nums" data-testid="trouble-white">{w.troubleMoves}</td>
                  <td className="py-1 text-right tabular-nums" data-testid="trouble-black">{b.troubleMoves}</td>
                </tr>
              </>
            );
          })()}
        </tbody>
      </table>

      {sentences.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="clock-insights">
          {sentences.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
      <p className="text-xs text-slate-600 dark:text-slate-400">
        Times come from the clock comments in the PGN. A move whose time cannot be worked out is shown as “–”, not as zero.
        {!classes && " Analyze the game to see how the clock relates to your mistakes."}
      </p>
    </section>
  );
}
