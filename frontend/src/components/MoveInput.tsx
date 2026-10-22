import { Chess } from "chess.js";
import { useState } from "react";

/** Read "Nf3", "exd5", "O-O" or "e2e4" in the given position. Null if it is not a legal move. */
export function parseTypedMove(fen: string, raw: string): { from: string; to: string } | null {
  const text = raw.trim();
  if (!text) return null;
  const tries: (() => ReturnType<Chess["move"]>)[] = [() => new Chess(fen).move(text)];
  const uci = text.toLowerCase().match(/^([a-h][1-8])([a-h][1-8])([qrbn])?$/);
  if (uci) tries.push(() => new Chess(fen).move({ from: uci[1], to: uci[2], promotion: uci[3] ?? "q" }));
  for (const attempt of tries) {
    try {
      const m = attempt();
      return { from: m.from, to: m.to };
    } catch {
      /* try the next reading */
    }
  }
  return null;
}

/**
 * A typed alternative to dragging a piece, so the board can be used from a keyboard or screen reader.
 * `onMove` returns whether the move was accepted.
 */
export function MoveInput({
  fen,
  onMove,
  disabled = false,
}: {
  fen: string;
  onMove: (from: string, to: string) => boolean;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <form
      className="mt-2"
      onSubmit={(e) => {
        e.preventDefault();
        const move = parseTypedMove(fen, text);
        if (!move) {
          setProblem(`"${text.trim()}" is not a legal move here.`);
          return;
        }
        setProblem(null);
        if (onMove(move.from, move.to)) setText("");
      }}
    >
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Type your move</span>
        <div className="flex gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={disabled}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="e.g. Nf3 or e2e4"
            aria-invalid={!!problem}
            aria-describedby={problem ? "move-input-problem" : undefined}
            className="min-w-0 flex-1 rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={disabled || !text.trim()}
            className="min-h-11 rounded border border-slate-300 px-3 text-sm font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            Play
          </button>
        </div>
      </label>
      {problem && (
        <p id="move-input-problem" role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">
          {problem}
        </p>
      )}
    </form>
  );
}
