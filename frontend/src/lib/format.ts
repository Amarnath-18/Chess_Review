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

/** "about 40 seconds", "about 1½ minutes", "about 25 minutes", "about 1 h 10 min". Rough on purpose. */
export function durationText(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 10) return "a few seconds";
  if (seconds < 55) return `about ${Math.round(seconds / 5) * 5} seconds`;
  if (seconds < 90) return "about a minute";
  const minutes = seconds / 60;
  if (minutes < 5) {
    const half = Math.round(minutes * 2) / 2;
    const whole = Math.floor(half);
    return `about ${whole > 0 ? whole : ""}${half % 1 ? "½" : ""} minutes`.replace("about 1 minutes", "about 1 minute");
  }
  if (minutes < 60) return `about ${Math.round(minutes)} minutes`;
  const h = Math.floor(minutes / 60);
  const m = Math.round((minutes - h * 60) / 5) * 5;
  return m === 0 || m === 60 ? `about ${h + (m === 60 ? 1 : 0)} h` : `about ${h} h ${m} min`;
}

/** Exact-ish length of a finished run: "41 s", "2 min 5 s". */
export function runTookText(start: string, end: string | null): string {
  if (!end) return "";
  const s = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}
