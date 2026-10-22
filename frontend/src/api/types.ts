export type AnalysisStatus = "none" | "queued" | "running" | "completed" | "failed";
export type JobStatus = "queued" | "running" | "completed" | "failed";

export type MoveClass =
  | "brilliant"
  | "great"
  | "best"
  | "excellent"
  | "good"
  | "inaccuracy"
  | "mistake"
  | "blunder";

export interface Job {
  id: string;
  game_id: string;
  status: JobStatus;
  progress_done: number;
  progress_total: number;
  attempts: number;
  max_attempts: number;
  error: string | null;
  run_id: string | null;
  params: { depth?: number | null; nodes?: number | null; multipv?: number };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface GameSummary {
  id: string;
  source: string;
  external_id: string | null;
  white: string;
  black: string;
  white_elo: number | null;
  black_elo: number | null;
  result: string;
  played_at: string | null;
  time_control: string | null;
  opening_name: string | null;
  eco: string | null;
  event: string | null;
  ply_count: number;
  created_at: string;
  analysis_status: AnalysisStatus;
  has_analysis: boolean;
}

export interface GameMove {
  ply: number;
  san: string;
  uci: string;
  fen: string; // position after this move
}

export interface GameDetail extends GameSummary {
  pgn: string;
  start_fen: string;
  moves: GameMove[];
  latest_job: Job | null;
}

export interface GameList {
  items: GameSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** White's perspective. All null = unavailable (NOT a draw). */
export interface Evaluation {
  cp: number | null;
  mate: number | null;
  terminal_result: string | null;
  display: string | null;
  win_pct: number | null;
}

export interface AltLine {
  move_uci: string | null;
  move_san: string | null;
  eval: Evaluation | null;
}

/** One engine line from a position (rank 1 = the engine's first choice). */
export interface EngineLine {
  rank: number;
  move_uci: string | null;
  move_san: string | null;
  eval: Evaluation;
  pv_san: string[];
}

export interface PositionAnalysis {
  ply: number;
  fen: string;
  eval: Evaluation;
  depth: number | null;
  best_move_uci: string | null;
  best_move_san: string | null;
  pv_san: string[];
  lines: EngineLine[];
  alt: AltLine | null;
  played_move_uci: string | null;
  played_move_san: string | null;
  classification: MoveClass | null;
  loss_pct: number | null;
  missed_win: boolean;
  is_sacrifice: boolean;
}

export type ClassCounts = Record<MoveClass, number>;

export interface ReviewSummary {
  complete: boolean;
  total_moves: number;
  analyzed_moves: number;
  unanalyzed_moves: number;
  counts: { white: ClassCounts; black: ClassCounts };
  missed_wins: { white: number; black: number };
  swings: { ply: number; delta_white: number }[];
  key_positions: { ply: number; reasons: string[] }[];
}

export interface Analysis {
  run: {
    id: string;
    status: string;
    engine_name: string;
    depth: number | null;
    nodes: number | null;
    multipv: number;
    class_config_hash: string;
    class_config: Record<string, number>;
    started_at: string;
    finished_at: string | null;
  };
  summary: ReviewSummary;
  positions: PositionAnalysis[];
}

export interface AnalysisStart {
  cached: boolean;
  job: Job | null;
  run_id: string | null;
}

export interface ImportResult {
  imported: GameSummary[];
  duplicates: { index: number; game: GameSummary }[];
  errors: { index: number; message: string }[];
  detail?: string;
}

export type ExternalSource = "chesscom" | "lichess";

/** One game found on Chess.com / Lichess, before anything is saved. */
export interface PreviewGame {
  external_id: string;
  url: string | null;
  white: string;
  black: string;
  white_elo: number | null;
  black_elo: number | null;
  result: string;
  played_at: string | null;
  time_control: string | null;
  opening_name: string | null;
  ply_count: number | null;
  already_imported: boolean;
  importable: boolean;
  problem: string | null;
}

export interface PreviewResult {
  source: ExternalSource;
  username: string;
  games: PreviewGame[];
  skipped_archives: number;
  note: string | null;
}

export interface Settings {
  default_depth: number;
  default_multipv: number;
  import_count: number;
  max_depth: number;
  max_multipv: number;
  retention_days: number;
}

export type SettingsPatch = Partial<Pick<Settings, "default_depth" | "default_multipv" | "import_count">>;

/** Filters shared by the history list and the PGN export. */
export interface GameQuery {
  q?: string;
  source?: string;
  result?: string;
  analyzed?: "yes" | "no";
  sort?: "played" | "added";
  from?: string;
  to?: string;
  page?: number;
}
