export interface MoveCell {
  ply: number;
  san: string;
}
export interface MoveRow {
  number: number;
  white?: MoveCell;
  black?: MoveCell;
}

/** Group plies into numbered rows, honouring a start position where Black moves first. */
export function buildRows(moves: MoveCell[], startFen: string): MoveRow[] {
  const parts = startFen.split(" ");
  let white = parts[1] !== "b";
  let number = parseInt(parts[5] ?? "1", 10) || 1;
  const rows: MoveRow[] = [];
  let row: MoveRow | null = null;
  for (const m of moves) {
    const cell = { ply: m.ply, san: m.san };
    if (white) {
      row = { number, white: cell };
      rows.push(row);
    } else {
      if (row && row.number === number && !row.black) row.black = cell;
      else {
        row = { number, black: cell };
        rows.push(row);
      }
      number += 1;
    }
    white = !white;
  }
  return rows;
}

/** "12. Nf3" or "12... Nc6" for the move that produced `ply`. */
export function plyLabel(ply: number, san: string, startFen: string): string {
  if (ply <= 0) return "Start position";
  const parts = startFen.split(" ");
  const whiteFirst = parts[1] !== "b";
  const first = parseInt(parts[5] ?? "1", 10) || 1;
  const half = (whiteFirst ? 0 : 1) + (ply - 1);
  const number = first + Math.floor(half / 2);
  return half % 2 === 0 ? `${number}. ${san}` : `${number}... ${san}`;
}

export const clampPly =(ply: number, max: number) => Math.max(0, Math.min(max, ply));
