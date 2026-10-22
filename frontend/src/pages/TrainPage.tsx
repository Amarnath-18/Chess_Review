import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAnswerPuzzle, useTrain } from "../api/hooks";
import type { Puzzle, PuzzleAnswer } from "../api/types";
import { Board } from "../components/Board";
import { Card } from "../components/Card";
import { MoveInput } from "../components/MoveInput";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { judgeMove } from "../lib/puzzle";

function Counts({ due, total, mastered }: { due: number; total: number; mastered: number }) {
  return (
    <p className="text-sm text-slate-600 dark:text-slate-400" data-testid="train-counts">
      {due} due now · {total} puzzle{total === 1 ? "" : "s"} in all · {mastered} well learned
    </p>
  );
}

function Solving({ puzzle, due, total, mastered }: { puzzle: Puzzle; due: number; total: number; mastered: number }) {
  const qc = useQueryClient();
  const answer = useAnswerPuzzle();
  const [result, setResult] = useState<PuzzleAnswer | null>(null);
  const [fenShown, setFenShown] = useState(puzzle.fen);

  const submit = (from: string, to: string) => {
    if (result || answer.isPending) return false;
    const move = judgeMove(puzzle.fen, from, to);
    if (!move) return false;
    setFenShown(move.fenAfter);
    answer.mutate({ id: puzzle.id, uci: move.uci }, { onSuccess: setResult });
    return true;
  };
  const next = () => {
    setResult(null);
    setFenShown(puzzle.fen);
    answer.reset();
    qc.invalidateQueries({ queryKey: ["train"] });
  };

  const arrows =
    result && !result.correct
      ? [{ from: result.best_uci.slice(0, 2), to: result.best_uci.slice(2, 4), color: "rgb(22, 163, 74)" }]
      : [];

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <Board fen={result && !result.correct ? puzzle.fen : fenShown} orientation={puzzle.side_to_move} arrows={arrows} onMove={submit} />
        {!result && <MoveInput fen={puzzle.fen} onMove={submit} disabled={answer.isPending} />}
      </div>
      <Card>
        <h2 className="text-lg font-semibold">
          {puzzle.side_to_move === "white" ? "White" : "Black"} to move
        </h2>
        <Counts due={due} total={total} mastered={mastered} />
        {!result ? (
          <p className="mt-3 text-sm" data-testid="puzzle-prompt">
            In your own game you went wrong here. Find the move you should have played.
          </p>
        ) : (
          <div className="mt-3 space-y-2 text-sm" role="status" data-testid="puzzle-result">
            <p className={`text-base font-semibold ${result.correct ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-300"}`}>
              {result.correct ? "Correct!" : "Not quite."}
            </p>
            {!result.correct && (
              <p>
                The engine's choice was <strong>{result.best_san}</strong>
                {result.line_san.length > 1 && <> ({result.line_san.slice(0, 4).join(" ")})</>}.
              </p>
            )}
            <p className="text-slate-600 dark:text-slate-400">
              In the game you played {result.played_san ?? result.played_uci}.{" "}
              <Link className="text-blue-600 underline dark:text-blue-400" to={`/games/${result.game_id}`}>
                Open the game
              </Link>
            </p>
            <p className="text-slate-600 dark:text-slate-400">
              {result.correct
                ? "It will come back later, after a longer gap."
                : "It will come back soon so you can try again."}
            </p>
            <button
              type="button"
              onClick={next}
              className="min-h-11 rounded bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700"
            >
              {result.due > 0 ? `Next puzzle (${result.due} due)` : "Finish"}
            </button>
          </div>
        )}
        {answer.error && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {(answer.error as Error).message}
          </p>
        )}
      </Card>
    </div>
  );
}

/** Puzzles made from your own mistakes in analyzed games, repeated on a spaced schedule. */
export default function TrainPage() {
  useDocumentTitle("Train");
  const train = useTrain();
  const t = train.data;

  return (
    <div className="mx-auto max-w-4xl px-4 py-4">
      <h1 className="mb-3 text-xl font-bold">Train</h1>
      {train.isLoading && <p role="status" className="text-sm text-slate-600 dark:text-slate-400">Looking through your games…</p>}
      {train.isError && (
        <p role="alert" className="text-sm text-red-600">
          Could not load your puzzles: {(train.error as Error).message}
        </p>
      )}
      {t?.needs_names && (
        <Card>
          <p className="text-sm">
            To make puzzles from <em>your</em> mistakes the app needs to know which player you are. Add your name
            (as it appears in your games) in{" "}
            <Link className="text-blue-600 underline dark:text-blue-400" to="/settings">
              Settings
            </Link>
            , or remember your Chess.com / Lichess account on the home page.
          </p>
        </Card>
      )}
      {t && !t.needs_names && t.total === 0 && (
        <Card>
          <p className="text-sm" data-testid="no-puzzles">
            No puzzles yet. They come from analyzed games where you made a clear mistake and the engine's best move
            was clearly better than the rest. Analyze some of your games on the{" "}
            <Link className="text-blue-600 underline dark:text-blue-400" to="/games">
              Games page
            </Link>{" "}
            and come back.
          </p>
        </Card>
      )}
      {t && t.total > 0 && !t.next && (
        <Card>
          <p className="font-semibold" data-testid="all-done">All caught up.</p>
          <Counts due={t.due} total={t.total} mastered={t.mastered} />
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            Puzzles you solved return after a day, then a few days, then weeks. Missed ones come back within minutes.
          </p>
        </Card>
      )}
      {t?.next && <Solving key={t.next.id} puzzle={t.next} due={t.due} total={t.total} mastered={t.mastered} />}
    </div>
  );
}
