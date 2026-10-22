import type { MoveClass } from "../api/types";

export interface ClassMeta {
  label: string;
  glyph: string; // mark shown on the board and in the move list
  text: string; // Tailwind text colour
  bg: string; // Tailwind badge background
  dot: string;
  blurb: string; // one-line explanation for tooltips
}

/** Every move gets a mark. Colour is always paired with a glyph and a label. */
export const CLASS_META: Record<MoveClass, ClassMeta> = {
  brilliant: {
    label: "Brilliant", glyph: "!!", text: "text-brilliant-fg", bg: "bg-brilliant", dot: "bg-brilliant",
    blurb: "A best or nearly-best piece sacrifice that was not already needed to stay winning",
  },
  great: {
    label: "Great", glyph: "!", text: "text-great-fg", bg: "bg-great", dot: "bg-great",
    blurb: "The only good move, or a move critical to the outcome",
  },
  best: {
    label: "Best", glyph: "★", text: "text-best-fg", bg: "bg-best", dot: "bg-best",
    blurb: "The engine's first choice",
  },
  excellent: {
    label: "Excellent", glyph: "✓", text: "text-excellent-fg", bg: "bg-excellent", dot: "bg-excellent",
    blurb: "Almost as good as the best move",
  },
  good: {
    label: "Good", glyph: "○", text: "text-good-fg", bg: "bg-good", dot: "bg-good",
    blurb: "A fine move that gave up a little",
  },
  inaccuracy: {
    label: "Inaccuracy", glyph: "?!", text: "text-inaccuracy-fg", bg: "bg-inaccuracy", dot: "bg-inaccuracy",
    blurb: "A small slip",
  },
  mistake: {
    label: "Mistake", glyph: "?", text: "text-mistake-fg", bg: "bg-mistake", dot: "bg-mistake",
    blurb: "A clear error",
  },
  blunder: {
    label: "Blunder", glyph: "??", text: "text-blunder-fg", bg: "bg-blunder", dot: "bg-blunder",
    blurb: "A serious error",
  },
  book: {
    label: "Book", glyph: "▤", text: "text-book-fg", bg: "bg-book", dot: "bg-book",
    blurb: "A known opening move",
  },
};

export const CLASS_ORDER: MoveClass[] = [
  "brilliant",
  "great",
  "best",
  "book",
  "excellent",
  "good",
  "inaccuracy",
  "mistake",
  "blunder",
];

/** Classes that the review treats as errors worth revisiting. */
export const ERROR_CLASSES: MoveClass[] = ["inaccuracy", "mistake", "blunder"];

const REASON_LABELS: Record<string, string> = {
  missed_win: "Missed win",
  swing: "Large swing",
  large_loss: "Large evaluation loss",
};
export const reasonLabel = (r: string) => REASON_LABELS[r] ?? r;

/** Arrow colours for engine lines 1..5 on the board. */
export const LINE_COLORS = [
  "rgb(22, 163, 74)", // 1 green
  "rgb(37, 99, 235)", // 2 blue
  "rgb(234, 88, 12)", // 3 orange
  "rgb(147, 51, 234)", // 4 purple
  "rgb(100, 116, 139)", // 5 slate
];
export const LINE_DOT_CLASSES = ["bg-green-600", "bg-blue-600", "bg-orange-600", "bg-purple-600", "bg-slate-500"];
