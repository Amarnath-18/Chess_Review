import { Chess } from "chess.js";
import type {
  Analysis,
  EngineLine,
  Evaluation,
  GameDetail,
  Job,
  MoveClass,
  PositionAnalysis,
} from "../api/types";

export const GAME_ID = "11111111-1111-1111-1111-111111111111";
const SAN = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"];

export function makeGame(overrides: Partial<GameDetail> = {}): GameDetail {
  const chess = new Chess();
  const start_fen = chess.fen();
  const moves = SAN.map((san, i) => {
    const m = chess.move(san);
    return { ply: i + 1, san, uci: m.from + m.to + (m.promotion ?? ""), fen: chess.fen() };
  });
  return {
    id: GAME_ID,
    source: "pgn",
    external_id: null,
    white: "Alice",
    black: "Bob",
    white_elo: 1500,
    black_elo: 1480,
    result: "1-0",
    played_at: "2024-03-09",
    time_control: null,
    opening_name: "Italian Game",
    eco: "C50",
    event: null,
    ply_count: moves.length,
    created_at: "2024-03-10T00:00:00Z",
    analysis_status: "none",
    has_analysis: false,
    pgn: "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 1-0",
    start_fen,
    moves,
    latest_job: null,
    ...overrides,
  };
}

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "22222222-2222-2222-2222-222222222222",
    game_id: GAME_ID,
    status: "queued",
    progress_done: 0,
    progress_total: 7,
    attempts: 0,
    max_attempts: 2,
    error: null,
    run_id: null,
    params: { depth: 16, nodes: null, multipv: 2 },
    created_at: "2024-03-10T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}


/** Win% per ply, chosen so ply 4 is a big swing and ply 5 a blunder. */
const WIN = [52, 53, 54, 53, 20, 70, 68];

/** One class per move so tests can check every mark: great, best, excellent, good, blunder, best. */
export const CLASSES: (MoveClass | null)[] = [null, "great", "best", "excellent", "good", "blunder", "best"];

const LINE_MOVES = [
  { uci: "e2e4", san: "e4" },
  { uci: "d2d4", san: "d4" },
  { uci: "g1f3", san: "Nf3" },
  { uci: "c2c4", san: "c4" },
  { uci: "b1c3", san: "Nc3" },
];

const ev = (cp: number): Evaluation => ({
  cp,
  mate: null,
  terminal_result: null,
  display: `${cp >= 0 ? "+" : ""}${(cp / 100).toFixed(2)}`,
  win_pct: 50 + cp / 20,
});

/** `multipv` engine lines per position, best first. */
export function makeAnalysis(multipv = 3): Analysis {
  const game = makeGame();
  const fens = [game.start_fen, ...game.moves.map((m) => m.fen)];
  const positions: PositionAnalysis[] = fens.map((fen, ply) => {
    const lines: EngineLine[] = LINE_MOVES.slice(0, multipv).map((m, i) => ({
      rank: i + 1,
      move_uci: m.uci,
      move_san: m.san,
      eval: ev(Math.round((WIN[ply] - 50) * 10) - i * 25),
      pv_san: [m.san, "e5", "Nf3"].filter((s, j, a) => a.indexOf(s) === j),
    }));
    return {
      ply,
      fen,
      eval: {
        cp: Math.round((WIN[ply] - 50) * 10),
        mate: null,
        terminal_result: null,
        display: `${WIN[ply] >= 50 ? "+" : ""}${((WIN[ply] - 50) / 10).toFixed(2)}`,
        win_pct: WIN[ply],
      },
      depth: 16,
      best_move_uci: lines[0].move_uci,
      best_move_san: ply === 0 ? "e4" : lines[0].move_san,
      pv_san: lines[0].pv_san,
      lines,
      alt: lines[1] ? { move_uci: lines[1].move_uci, move_san: lines[1].move_san, eval: lines[1].eval } : null,
      played_move_uci: ply > 0 ? game.moves[ply - 1].uci : null,
      played_move_san: ply > 0 ? game.moves[ply - 1].san : null,
      classification: CLASSES[ply],
      loss_pct: ply === 5 ? 33.3 : 0,
      missed_win: ply === 5,
      is_sacrifice: false,
    };
  });
  const zero = { brilliant: 0, great: 0, best: 0, excellent: 0, good: 0, inaccuracy: 0, mistake: 0, blunder: 0 };
  return {
    run: {
      id: "run-1",
      status: "completed",
      engine_name: "Stockfish 17.1",
      depth: 16,
      nodes: null,
      multipv,
      class_config_hash: "abc",
      class_config: {},
      started_at: "2024-03-10T00:00:00Z",
      finished_at: "2024-03-10T00:01:00Z",
    },
    summary: {
      complete: true,
      total_moves: 6,
      analyzed_moves: 6,
      unanalyzed_moves: 0,
      counts: {
        white: { ...zero, great: 1, excellent: 1, blunder: 1 },
        black: { ...zero, best: 2, good: 1 },
      },
      missed_wins: { white: 1, black: 0 },
      swings: [{ ply: 5, delta_white: -33 }],
      key_positions: [{ ply: 5, reasons: ["missed_win", "large_loss"] }],
    },
    positions,
  };
}
