export type AnalysisStatus = "none" | "queued" | "running" | "completed" | "failed";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type MoveClass =
  | "brilliant"
  | "great"
  | "best"
  | "excellent"
  | "good"
  | "inaccuracy"
  | "mistake"
  | "blunder"
  | "book"; // an opening-book move: a quiet mark, not a quality verdict

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
  favorite?: boolean;
  tags?: string[];
  has_note?: boolean;
}

export interface GameMove {
  ply: number;
  san: string;
  uci: string;
  fen: string; // position after this move
}

export interface ClockInfo {
  ply: number;
  clock: number | null; // mover's remaining seconds after the move
  spent: number | null; // seconds the move took, when it can be worked out
  time_trouble: boolean;
}

export interface GameDetail extends GameSummary {
  pgn: string;
  start_fen: string;
  moves: GameMove[];
  clocks?: ClockInfo[] | null; // null/absent: the game has no clock comments
  latest_job: Job | null;
  note?: string | null;
  move_notes?: Record<string, string>; // ply -> note
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
  opening?: string | null; // opening name while the game is still in book
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
  accuracy?: { white: number | null; black: number | null };
  opening?: { eco: string; name: string; ply: number } | null;
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

/** A live preview of the running analysis: positions evaluated so far. Not a review. */
export interface PartialAnalysis {
  run: Analysis["run"];
  done: number;
  total: number;
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
  auto_analyzing?: number; // games queued for analysis automatically
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
  auto_analyze?: boolean;
  my_names?: string[];
  ai_available?: boolean;
  ai_explanations?: boolean;
  explain_level?: "beginner" | "intermediate" | "advanced";
  ai_provider?: string;
  explain_daily_limit?: number;
  max_depth: number;
  max_multipv: number;
  retention_days: number;
}

export type SettingsPatch = Partial<Pick<Settings, "default_depth" | "default_multipv" | "import_count" | "auto_analyze" | "my_names" | "ai_explanations" | "explain_level">>;

/** Filters shared by the history list and the PGN export. */
export interface GameQuery {
  q?: string;
  source?: string;
  result?: string;
  analyzed?: "yes" | "no";
  sort?: "played" | "added";
  from?: string;
  to?: string;
  favorite?: boolean;
  tag?: string;
  page?: number;
}

export interface Estimate {
  seconds: number | null; // central guess; null: node-limited search, not estimated
  seconds_low: number | null;
  seconds_high: number | null;
  positions: number;
  limit_seconds: number;
  exceeds_limit: boolean; // even the central guess is over the limit
  may_exceed_limit: boolean; // the top of the range is over the limit
  calibrated_from_runs: number;
}

// ---- analyze-all batches ----------------------------------------------------------------

export type BatchItemState = "pending" | "queued" | "done" | "failed" | "skipped" | "cancelled";

export interface BatchItem {
  game_id: string;
  white: string;
  black: string;
  state: BatchItemState;
  message: string | null;
  progress_done: number | null;
  progress_total: number | null;
}

export interface Batch {
  id: string;
  status: "running" | "completed" | "cancelled";
  params: { depth?: number | null; nodes?: number | null; multipv?: number };
  created_at: string;
  finished_at: string | null;
  total: number;
  counts: Record<BatchItemState, number>;
  items: BatchItem[];
}

/** Which games a batch covers: explicit ids, or the history filters. */
export interface BatchRequest {
  game_ids?: string[];
  filter?: { q?: string; source?: string; result?: string; date_from?: string; date_to?: string; favorite?: boolean; tag?: string };
  depth?: number;
  multipv?: number;
  only_unanalyzed?: boolean;
}

export interface BatchEstimate {
  games: number;
  skipped: number;
  positions: number;
  seconds: number | null;
  seconds_low: number | null;
  seconds_high: number | null;
  too_many: boolean;
  max_games: number;
  calibrated_from_runs: number;
}

// ---- remembered accounts ------------------------------------------------------------------

export interface LinkedSource {
  id: string;
  source: ExternalSource;
  username: string;
  created_at: string;
  last_checked_at: string | null;
}

export interface NewGames {
  source_id: string;
  source: ExternalSource;
  username: string;
  new_games: PreviewGame[];
  checked: number;
  already_saved: number;
  cannot_import: number;
  note: string | null;
  skipped_archives: number;
}

/** Fields of a game the owner can change. Tags replace the whole set. */
export interface GameUpdate {
  favorite?: boolean;
  note?: string | null;
  tags?: string[];
}

// ---- training and statistics ----------------------------------------------------------------

export interface Puzzle {
  id: string;
  fen: string;
  side_to_move: "white" | "black";
  game_id: string;
  ply: number;
  box: number;
}

export interface TrainStatus {
  needs_names: boolean;
  games_looked_at: number;
  new_puzzles: number;
  total: number;
  due: number;
  mastered: number;
  next: Puzzle | null;
}

export interface PuzzleAnswer {
  correct: boolean;
  best_uci: string;
  best_san: string | null;
  played_uci: string;
  played_san: string | null;
  line_san: string[];
  game_id: string;
  ply: number;
  box: number;
  due_at: string;
  due: number;
}

export interface StatBucket {
  key: string;
  label: string;
  games: number;
  moves: number;
  inaccuracies: number;
  mistakes: number;
  blunders: number;
  serious_per_100: number | null;
  reliable: boolean;
}

export interface OpeningStat {
  name: string;
  games: number;
  wins: number;
  draws: number;
  losses: number;
  accuracy: number | null;
  reliable: boolean;
}

export interface Stats {
  needs_names: boolean;
  games_analyzed: number;
  games_included: number;
  games_unidentified: number;
  min_games: number;
  min_moves: number;
  overall: StatBucket;
  by_phase: StatBucket[];
  by_color: StatBucket[];
  by_time_control: StatBucket[];
  openings: OpeningStat[];
  trend: { game_id: string; played_at: string | null; accuracy: number | null; color: string; opponent: string }[];
  highlights: string[];
}

// ---- access gate and AI explanations ---------------------------------------------------------

export interface AccessStatus {
  required: boolean; // this server asks for an invite code
  unlocked: boolean;
  label: string | null;
}

export interface Explanation {
  ply: number;
  text: string;
  /** "ai": written by the model and checked against the engine facts. "fallback": built from the facts alone. */
  source: "ai" | "fallback";
  motif: string | null;
  model: string;
  level: string;
  cached: boolean;
  remaining_today: number;
  created_at: string;
}

export interface Explanations {
  items: Explanation[];
  remaining_today: number;
}
