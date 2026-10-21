import type { Evaluation } from "../api/types";
import { evalText } from "../lib/format";

interface Props {
  evaluation: Evaluation | null; // null = no engine evaluation for what is on the board
  orientation: "white" | "black";
}

/** Vertical bar showing White's winning chances; unknown evaluations are striped, never 50%. */
export function EvalBar({ evaluation, orientation }: Props) {
  const pct = evaluation?.win_pct ?? null;
  const whiteOnBottom = orientation === "white";
  const label =
    pct !== null ? `White's winning chances ${Math.round(pct)}%` : "No evaluation for this position";

  // Put the number at the end of the bar that belongs to whoever is better.
  const whiteDominant = (pct ?? 50) >= 50;
  const atBottom = whiteDominant === whiteOnBottom;
  const labelPos =
    pct === null ? "top-1/2 -translate-y-1/2" : atBottom ? "bottom-1" : "top-1";
  const labelColor = pct === null || whiteDominant ? "text-slate-800" : "text-slate-100";

  return (
    <div
      role="img"
      aria-label={label}
      title={label}
      data-testid="eval-bar"
      className={`relative flex w-7 shrink-0 overflow-hidden rounded border border-slate-400 text-[10px] font-semibold dark:border-slate-600 ${
        whiteOnBottom ? "flex-col-reverse" : "flex-col"
      } ${
        pct !== null
          ? "bg-slate-800"
          : "bg-[repeating-linear-gradient(45deg,#94a3b8,#94a3b8_4px,#cbd5e1_4px,#cbd5e1_8px)]"
      }`}
    >
      {pct !== null && (
        <div className="bg-white transition-[height] duration-200" style={{ height: `${pct}%` }} />
      )}
      <span className={`absolute left-0 right-0 text-center ${labelPos} ${labelColor}`}>
        {evalText(evaluation)}
      </span>
    </div>
  );
}
