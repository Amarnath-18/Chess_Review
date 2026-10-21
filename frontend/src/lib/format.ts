import type { Evaluation, GameSummary } from "../api/types";

export const resultText = (r: string) => (r === "1/2-1/2" ? "½–½" : r === "*" ? "*" : r.replace("-", "–"));

export function resultDescription(r: string): string {
  if (r === "1-0") return "White won";
  if (r === "0-1") return "Black won";
  if (r === "1/2-1/2") return "Draw";
  return "Result unknown";
}

export const dateText = (d: string | null) =>
  d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Date unknown";

export const playerLabel = (name: string, elo: number | null) => (elo ? `${name} (${elo})` : name);

export const gameTitle = (g: Pick<GameSummary, "white" | "black">) => `${g.white} vs ${g.black}`;

/** Text for an evaluation; unavailable data is shown as such, never as 0.00. */
export const evalText = (e: Evaluation | null | undefined) => e?.display ?? "n/a";

export const SOURCE_LABEL: Record<string, string> = {
  pgn: "PGN",
  chesscom: "Chess.com",
  lichess: "Lichess",
};
