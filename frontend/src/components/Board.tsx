import { Chessboard } from "react-chessboard";
import type { MoveClass } from "../api/types";
import { useElementWidth } from "../hooks/useMeasure";
import { type ArrowSpec, badgePosition } from "../lib/board";
import { CLASS_META } from "../lib/quality";

interface Props {
  fen: string;
  orientation: "white" | "black";
  lastMove?: [string, string] | null;
  /** Engine lines to draw, best first (each its own colour). */
  arrows?: ArrowSpec[];
  /** Quality mark drawn on a square (the destination of the move just played). */
  mark?: { square: string; cls: MoveClass } | null;
  onMove: (from: string, to: string) => boolean;
}

const HIGHLIGHT = { backgroundColor: "rgba(250, 204, 21, 0.45)" };

export function Board({ fen, orientation, lastMove, arrows = [], mark, onMove }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(480);
  const size = Math.max(200, Math.min(width, 640));

  const squareStyles: Record<string, React.CSSProperties> = {};
  if (lastMove) {
    squareStyles[lastMove[0]] = HIGHLIGHT;
    squareStyles[lastMove[1]] = HIGHLIGHT;
  }
  const badge = mark ? badgePosition(mark.square, orientation, size) : null;
  const meta = mark ? CLASS_META[mark.cls] : null;

  return (
    <div ref={ref} className="w-full" data-testid="board" data-fen={fen}>
      <div className="relative" style={{ width: size, height: size }}>
        <Chessboard
          id="review-board"
          position={fen}
          boardOrientation={orientation}
          boardWidth={size}
          animationDuration={120}
          customSquareStyles={squareStyles}
          customArrows={arrows.map((a) => [a.from as never, a.to as never, a.color])}
          customDarkSquareStyle={{ backgroundColor: "#769656" }}
          customLightSquareStyle={{ backgroundColor: "#eeeed2" }}
          onPieceDrop={(from, to) => onMove(from, to)}
        />
        {badge && meta && mark && (
          <div
            role="img"
            aria-label={`${meta.label} move`}
            title={`${meta.label}: ${meta.blurb}`}
            data-testid="move-mark"
            data-class={mark.cls}
            data-square={mark.square}
            className={`pointer-events-none absolute flex items-center justify-center rounded-full border-2 border-white text-[11px] font-extrabold leading-none text-white shadow ${meta.bg}`}
            style={{ left: badge.left, top: badge.top, width: badge.diameter, height: badge.diameter }}
          >
            {meta.glyph}
          </div>
        )}
      </div>
    </div>
  );
}
