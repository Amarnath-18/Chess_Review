import { useState } from "react";
import type { PositionAnalysis } from "../api/types";
import { areaPath, buildGraphPoints, linePath, plyAtX, segments } from "../lib/graph";

interface Props {
  positions: PositionAnalysis[];
  currentPly: number;
  swings: { ply: number; delta_white: number }[];
  onSelect: (ply: number) => void;
}

const W = 600;
const H = 140;

/** White's winning chances over the game. Up = better for White. Click to jump to a move. */
export function EvalGraph({ positions, currentPly, swings, onSelect }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const total = positions.length - 1;
  const points = buildGraphPoints(positions, W, H);
  const segs = segments(points);
  const missing = points.filter((p) => p.y === null).length;

  const plyFromEvent = (e: React.PointerEvent<SVGSVGElement> | React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return plyAtX(e.clientX - rect.left, rect.width, total);
  };

  const shown = hover ?? currentPly;
  const cur = points[currentPly];
  const hp = positions[shown];

  return (
    <figure className="m-0">
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>Evaluation (White better ↑)</span>
        <span aria-live="off">
          {hp
            ? `${shown === 0 ? "Start" : `Move ${Math.ceil(shown / 2)}${shown % 2 ? "" : "…"} ${hp.played_move_san ?? ""}`} · ${hp.eval.display ?? "n/a"}`
            : ""}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full cursor-pointer touch-none rounded border border-slate-300 bg-slate-700 dark:border-slate-600"
        role="img"
        aria-label={`Evaluation graph with ${total} moves. Click to select a move.`}
        data-testid="eval-graph"
        onClick={(e) => onSelect(plyFromEvent(e))}
        onPointerMove={(e) => setHover(plyFromEvent(e))}
        onPointerLeave={() => setHover(null)}
      >
        {segs.map((s, i) => (
          <g key={i}>
            {s.length > 1 && <path d={areaPath(s, H)} className="fill-white" />}
            {s.length > 1 && <path d={linePath(s)} className="fill-none stroke-slate-400" strokeWidth={1.5} />}
            {s.length === 1 && <circle cx={s[0].x} cy={s[0].y as number} r={2.5} className="fill-white" />}
          </g>
        ))}
        <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="stroke-slate-500" strokeDasharray="4 4" />

        {swings.map((s) => (
          <line
            key={s.ply}
            x1={(s.ply / Math.max(1, total)) * W}
            x2={(s.ply / Math.max(1, total)) * W}
            y1={H - 10}
            y2={H}
            className="stroke-orange-500"
            strokeWidth={3}
          >
            <title>{`Large swing at move ${Math.ceil(s.ply / 2)} (${s.delta_white > 0 ? "+" : ""}${s.delta_white} pts for White)`}</title>
          </line>
        ))}

        {points
          .filter((p) => p.mate && p.y !== null)
          .map((p) => (
            <rect
              key={p.ply}
              x={p.x - 3}
              y={(p.y as number) - 3}
              width={6}
              height={6}
              transform={`rotate(45 ${p.x} ${p.y})`}
              className="fill-red-500 stroke-white"
            >
              <title>Forced mate</title>
            </rect>
          ))}

        {cur && (
          <g data-testid="graph-cursor" data-ply={currentPly}>
            <line x1={cur.x} x2={cur.x} y1={0} y2={H} className="stroke-blue-400" strokeWidth={2} />
            {cur.y !== null && <circle cx={cur.x} cy={cur.y} r={4} className="fill-blue-500 stroke-white" />}
          </g>
        )}
      </svg>
      {missing > 0 && (
        <figcaption className="mt-1 text-xs text-slate-500">
          {missing} position{missing > 1 ? "s have" : " has"} no evaluation and {missing > 1 ? "are" : "is"} left out of the line.
        </figcaption>
      )}
    </figure>
  );
}
