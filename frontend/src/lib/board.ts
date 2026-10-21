export type Orientation = "white" | "black";

/** Top-left corner of a square (e.g. "e4") on a board of `size` pixels. */
export function squareOrigin(
  square: string,
  orientation: Orientation,
  size: number,
): { x: number; y: number } {
  const file = square.charCodeAt(0) - 97; // a..h -> 0..7
  const rank = parseInt(square[1], 10) - 1; // 1..8 -> 0..7
  const col = orientation === "white" ? file : 7 - file;
  const row = orientation === "white" ? 7 - rank : rank;
  const sq = size / 8;
  return { x: col * sq, y: row * sq };
}

/** Where to put a move-quality badge: the top-right corner of the destination square,
 *  kept inside the board. */
export function badgePosition(
  square: string,
  orientation: Orientation,
  size: number,
): { left: number; top: number; diameter: number } {
  const sq = size / 8;
  const diameter = Math.max(18, Math.round(sq * 0.46));
  const { x, y } = squareOrigin(square, orientation, size);
  return {
    left: Math.min(x + sq - diameter * 0.72, size - diameter),
    top: Math.max(y - diameter * 0.28, 0),
    diameter,
  };
}

export interface ArrowSpec {
  from: string;
  to: string;
  color: string;
}
