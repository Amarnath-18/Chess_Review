import { useEffect, useMemo, useRef } from "react";
import type { GameMove, MoveClass } from "../api/types";
import { buildRows } from "../lib/moves";
import { CLASS_META } from "../lib/quality";

interface Props {
  moves: GameMove[];
  startFen: string;
  currentPly: number;
  classes?: (MoveClass | null)[]; // indexed by ply
  dimmed?: boolean; // true while a variation is shown
  onSelect: (ply: number) => void;
}

export function MoveList({ moves, startFen, currentPly, classes, dimmed, onSelect }: Props) {
  const rows = useMemo(() => buildRows(moves, startFen), [moves, startFen]);
  const boxRef = useRef<HTMLDivElement>(null);

  // Keep the selected move visible without scrolling the whole page.
  useEffect(() => {
    const box = boxRef.current;
    const el = box?.querySelector<HTMLElement>(`[data-ply="${currentPly}"]`);
    if (!box || !el) return;
    const top = el.offsetTop - box.offsetTop;
    if (top < box.scrollTop) box.scrollTop = top - 4;
    else if (top + el.offsetHeight > box.scrollTop + box.clientHeight)
      box.scrollTop = top + el.offsetHeight - box.clientHeight + 4;
  }, [currentPly]);

  const cell = (c?: { ply: number; san: string }) => {
    if (!c) return <span />;
    const cls = classes?.[c.ply] ?? null;
    const meta = cls ? CLASS_META[cls] : null;
    const selected = c.ply === currentPly;
    return (
      <button
        type="button"
        data-ply={c.ply}
        aria-current={selected ? "true" : undefined}
        aria-label={`${c.san}${meta ? `, ${meta.label}` : ""}`}
        onClick={() => onSelect(c.ply)}
        className={`flex items-center gap-1 rounded px-2 py-1 text-left text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-700 ${
          selected
            ? dimmed
              ? "bg-slate-200 dark:bg-slate-700"
              : "bg-blue-600 text-white hover:bg-blue-600 dark:hover:bg-blue-600"
            : ""
        }`}
      >
        <span>{c.san}</span>
        {meta && (
          <span
            className={`text-xs font-bold ${selected && !dimmed ? "text-white" : meta.text}`}
            aria-hidden="true"
            title={meta.label}
            data-class={cls}
          >
            {meta.glyph}
          </span>
        )}
      </button>
    );
  };

  return (
    <div
      ref={boxRef}
      className="relative max-h-72 overflow-y-auto rounded border border-slate-200 dark:border-slate-700"
      role="group"
      aria-label="Moves"
    >
      <div className="grid grid-cols-[2.5rem_1fr_1fr] items-center gap-y-0.5 p-1">
        {rows.map((r) => (
          <div key={r.number} className="contents">
            <span className="px-1 text-right text-xs text-slate-500">{r.number}.</span>
            {cell(r.white)}
            {cell(r.black)}
          </div>
        ))}
      </div>
    </div>
  );
}
