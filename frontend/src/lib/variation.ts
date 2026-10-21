import { Chess } from "chess.js";

/**
 * A local, throw-away line explored from a position of the real game.
 * It lives only in component state: it is never sent to the server, so it cannot
 * alter the saved game or its analysis.
 */
export interface Variation {
  basePly: number;
  /** fens[i] = position after i variation moves; fens[0] is the base position. */
  fens: string[];
  sans: string[];
  ucis: string[];
  index: number; // 0..sans.length
}

export const startVariation = (basePly: number, baseFen: string): Variation => ({
  basePly,
  fens: [baseFen],
  sans: [],
  ucis: [],
  index: 0,
});

function tryMove(fen: string, move: string | { from: string; to: string; promotion?: string }) {
  try {
    const c = new Chess(fen);
    const m = c.move(move);
    return { san: m.san, uci: m.from + m.to + (m.promotion ?? ""), fen: c.fen() };
  } catch {
    return null; // illegal
  }
}

/** Play a move from the variation's current position, discarding any moves after it. */
export function playMove(
  v: Variation,
  from: string,
  to: string,
  promotion: string = "q",
): Variation | null {
  const m = tryMove(v.fens[v.index], { from, to, promotion });
  if (!m) return null;
  return {
    ...v,
    fens: [...v.fens.slice(0, v.index + 1), m.fen],
    sans: [...v.sans.slice(0, v.index), m.san],
    ucis: [...v.ucis.slice(0, v.index), m.uci],
    index: v.index + 1,
  };
}

/** Build a variation by playing a UCI line (e.g. the engine's PV) up to `upTo` moves. */
export function fromLine(
  basePly: number,
  baseFen: string,
  ucis: string[],
  upTo: number = ucis.length,
): Variation | null {
  let v = startVariation(basePly, baseFen);
  for (const uci of ucis.slice(0, upTo)) {
    const next = playMove(v, uci.slice(0, 2), uci.slice(2, 4), uci[4] ?? "q");
    if (!next) return v.sans.length ? v : null; // stop at the first illegal move
    v = next;
  }
  return v;
}

/** Build a variation from a SAN line (e.g. the engine's PV) up to `upTo` moves. */
export function fromSans(
  basePly: number,
  baseFen: string,
  sans: string[],
  upTo: number = sans.length,
): Variation | null {
  let v = startVariation(basePly, baseFen);
  for (const san of sans.slice(0, upTo)) {
    const m = tryMove(v.fens[v.index], san);
    if (!m) break; // stop at the first move that does not apply
    v = {
      ...v,
      fens: [...v.fens, m.fen],
      sans: [...v.sans, m.san],
      ucis: [...v.ucis, m.uci],
      index: v.index + 1,
    };
  }
  return v.sans.length ? v : null;
}

export const stepVariation =(v: Variation, delta: number): Variation => ({
  ...v,
  index: Math.max(0, Math.min(v.sans.length, v.index + delta)),
});

export const currentFen = (v: Variation) => v.fens[v.index];

export const lastMoveSquares = (v: Variation): [string, string] | null => {
  if (v.index === 0) return null;
  const uci = v.ucis[v.index - 1];
  return [uci.slice(0, 2), uci.slice(2, 4)];
};

/** "12. Nf3 Nc6" style text for a variation, with correct move numbers from the base FEN. */
export function formatVariation(v: Variation): { text: string; san: string; at: number }[] {
  const parts = v.fens[0].split(" ");
  let white = parts[1] === "w";
  let number = parseInt(parts[5] ?? "1", 10) || 1;
  return v.sans.map((san, i) => {
    const label = white ? `${number}.` : i === 0 ? `${number}...` : "";
    if (!white) number += 1;
    white = !white;
    return { text: label ? `${label} ${san}` : san, san, at: i + 1 };
  });
}
