import type { PositionAnalysis } from "../api/types";

/** A position that has not been evaluated yet: every field empty, never a fake "0.00". */
function placeholder(ply: number, fen: string): PositionAnalysis {
  return {
    ply,
    fen,
    eval: { cp: null, mate: null, terminal_result: null, display: null, win_pct: null },
    depth: null,
    best_move_uci: null,
    best_move_san: null,
    pv_san: [],
    lines: [],
    alt: null,
    played_move_uci: null,
    played_move_san: null,
    classification: null,
    loss_pct: null,
    missed_win: false,
    is_sacrifice: false,
  };
}

/** The positions evaluated so far, padded with empty placeholders to the full game length so the
 * graph and move list keep their shape while the analysis grows. */
export function padPositions(done: PositionAnalysis[], fens: string[]): PositionAnalysis[] {
  return fens.map((fen, ply) => done[ply] ?? placeholder(ply, fen));
}
