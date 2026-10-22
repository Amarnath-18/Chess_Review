import { Link } from "react-router-dom";
import { useExplain, useExplanations, useSettings } from "../api/hooks";
import type { Explanation, PositionAnalysis } from "../api/types";
import { MoveChips } from "./EnginePanel";

/** Whether the person has AI explanations on and the server offers them. */
export function useAiReady() {
  const s = useSettings().data;
  return { available: !!s?.ai_available, on: !!s?.ai_available && !!s?.ai_explanations, settings: s };
}

/** The label that must always accompany an explanation: who wrote it and how far to trust it. */
export function ExplanationNote({ source }: { source: Explanation["source"] }) {
  return (
    <p className="mt-1 text-xs text-slate-600 dark:text-slate-400" data-testid="ai-note">
      {source === "ai"
        ? "Written by an AI from the engine's analysis. It can be wrong; the engine's lines are the facts."
        : "Built from the engine's data: the AI's answer could not be verified, so this is a plain summary."}
    </p>
  );
}

/** "Explain this move" for the move on the board, with the engine's own line right beside the answer. */
export function ExplainBox({
  gameId,
  ply,
  previous,
  onExplore,
}: {
  gameId: string;
  ply: number;
  previous: PositionAnalysis | null;
  onExplore: (basePly: number, sans: string[], upTo: number) => void;
}) {
  const ai = useAiReady();
  const list = useExplanations(gameId, ai.on);
  const explain = useExplain(gameId);
  if (!ai.available) return null;
  if (!ai.on) {
    return (
      <p className="text-xs text-slate-600 dark:text-slate-400">
        AI explanations are available.{" "}
        <Link to="/settings" className="text-blue-600 underline dark:text-blue-400">
          Turn them on in Settings
        </Link>
        .
      </p>
    );
  }
  const stored = list.data?.items.find((i) => i.ply === ply);
  const remaining = explain.data?.remaining_today ?? list.data?.remaining_today;
  const best = previous?.lines[0];

  return (
    <section aria-label="AI explanation" className="rounded border border-slate-200 p-2 dark:border-slate-700" data-testid="explain-box">
      <h3 className="text-sm font-semibold">AI explanation</h3>
      {stored ? (
        <>
          <p className="mt-1 text-sm" data-testid="ai-text">
            {stored.text}
          </p>
          <ExplanationNote source={stored.source} />
          {previous && best && best.pv_san.length > 0 && (
            <div className="mt-2">
              <div className="mb-1 text-xs text-slate-600 dark:text-slate-400">
                Engine's line from the position before ({best.eval.display}):
              </div>
              <MoveChips basePly={previous.ply} sans={best.pv_san} label="Engine line behind the explanation" onExplore={onExplore} />
            </div>
          )}
        </>
      ) : (
        <div className="mt-1">
          <button
            type="button"
            disabled={explain.isPending || list.isLoading}
            onClick={() => explain.mutate(ply)}
            className="min-h-11 rounded border border-blue-600 px-3 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-60 dark:border-blue-400 dark:text-blue-300 dark:hover:bg-blue-950"
          >
            {explain.isPending ? "Thinking…" : "Explain this move"}
          </button>
          {remaining !== undefined && (
            <span className="ml-2 text-xs text-slate-600 dark:text-slate-400">{remaining} left today</span>
          )}
        </div>
      )}
      {explain.error && (
        <p role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">
          {(explain.error as Error).message}
        </p>
      )}
    </section>
  );
}
