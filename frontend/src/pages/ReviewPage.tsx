import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, gamePgnUrl } from "../api/client";
import { useAnalysis, useGame, useJobProgress, usePartialAnalysis } from "../api/hooks";
import type { Analysis, GameDetail, Job, MoveClass, PartialAnalysis } from "../api/types";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { Board } from "../components/Board";
import { Card } from "../components/Card";
import { ClockPanel } from "../components/ClockPanel";
import { EnginePanel } from "../components/EnginePanel";
import { ExplainBox } from "../components/ExplainBox";
import { GameNotes } from "../components/GameNotes";
import { KeyMoments } from "../components/KeyMoments";
import { MoveInput } from "../components/MoveInput";
import { EvalBar } from "../components/EvalBar";
import { EvalGraph } from "../components/EvalGraph";
import { MoveList } from "../components/MoveList";
import { NavControls } from "../components/NavControls";
import { PlayerBar } from "../components/PlayerBar";
import { SummaryCard } from "../components/SummaryCard";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useKeyboardNav } from "../hooks/useKeyboardNav";
import { useMediaQuery } from "../hooks/useMeasure";
import { dateText, resultDescription, resultText, SOURCE_LABEL } from "../lib/format";
import type { ArrowSpec } from "../lib/board";
import { clampPly, plyLabel } from "../lib/moves";
import { padPositions } from "../lib/preview";
import { judgeRetry, retryMessage, type RetryResult } from "../lib/retry";
import { LINE_COLORS } from "../lib/quality";
import {
  currentFen,
  formatVariation,
  fromSans,
  lastMoveSquares,
  playMove,
  startVariation,
  stepVariation,
  type Variation,
} from "../lib/variation";

export default function ReviewPage() {
  const { id = "" } = useParams();
  const gameQ = useGame(id);
  const job = useJobProgress(id, gameQ.data?.latest_job);
  const analysisQ = useAnalysis(id, !!gameQ.data?.has_analysis);
  // While a first analysis runs, show what has been evaluated so far (clearly marked as not final).
  const previewing = job?.status === "running" && !analysisQ.data;
  const partialQ = usePartialAnalysis(id, previewing);

  if (gameQ.isLoading) return <p role="status" className="p-6 text-slate-600 dark:text-slate-400">Loading game…</p>;
  if (gameQ.error || !gameQ.data) {
    const notFound = gameQ.error instanceof ApiError && gameQ.error.status === 404;
    return (
      <div role="alert" className="p-6">
        <p className="font-semibold">{notFound ? "Game not found" : "Could not load this game."}</p>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {notFound
            ? "It may have been deleted, or it belongs to a different browser session."
            : (gameQ.error as Error | null)?.message}
        </p>
        <Link to="/" className="mt-2 inline-block text-blue-600 underline dark:text-blue-400">
          Back to your games
        </Link>
      </div>
    );
  }
  return (
    <Review
      key={gameQ.data.id}
      game={gameQ.data}
      job={job}
      analysis={analysisQ.data}
      partial={previewing ? partialQ.data : undefined}
    />
  );
}

type Tab = "moves" | "graph" | "engine" | "summary" | "time" | "notes";
const BASE_TABS: { id: Tab; label: string }[] = [
  { id: "moves", label: "Moves" },
  { id: "graph", label: "Graph" },
  { id: "engine", label: "Engine" },
  { id: "summary", label: "Summary" },
];
const TIME_TAB: { id: Tab; label: string } = { id: "time", label: "Time" };
const NOTES_TAB: { id: Tab; label: string } = { id: "notes", label: "Notes" };

function Review({
  game,
  job,
  analysis,
  partial,
}: {
  game: GameDetail;
  job: Job | null;
  analysis: Analysis | undefined;
  partial: PartialAnalysis | undefined;
}) {
  useDocumentTitle(`${game.white} vs ${game.black}`);
  const [ply, setPly] = useState(0);
  const [variation, setVariation] = useState<Variation | null>(null);
  // "Try to find a better move": the board returns to the position before a mistake and the try is judged
  // against the saved engine lines. Never saved, never sent anywhere.
  const [retry, setRetry] = useState<{ result: RetryResult | null; revealed: boolean } | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [showArrow, setShowArrow] = useState(true);
  const [linesChoice, setLinesChoice] = useState(3); // how many engine lines to display
  const [tab, setTab] = useState<Tab>("moves");
  const wide = useMediaQuery("(min-width: 1024px)");

  const maxPly = game.moves.length;
  const fens = useMemo(() => [game.start_fen, ...game.moves.map((m) => m.fen)], [game]);
  // A live preview is only used when there is no finished review to show.
  const preview = analysis ? undefined : partial;
  const positions = useMemo(
    () => analysis?.positions ?? (preview ? padPositions(preview.positions, fens) : undefined),
    [analysis, preview, fens],
  );
  const evaluated = analysis ? maxPly + 1 : (preview?.positions.length ?? 0);
  const here = positions && ply < evaluated ? positions[ply] : undefined;
  const label = (p: number) => plyLabel(p, game.moves[p - 1]?.san ?? "", game.start_fen);

  const classes = useMemo(
    () => (positions ? positions.map((p) => p.classification as MoveClass | null) : undefined),
    [positions],
  );

  const selectPly = (p: number) => {
    setVariation(null);
    setPly(clampPly(p, maxPly));
  };

  const nav = {
    prev: () =>
      variation
        ? variation.index > 0
          ? setVariation(stepVariation(variation, -1))
          : setVariation(null)
        : setPly((p) => clampPly(p - 1, maxPly)),
    next: () =>
      variation ? setVariation(stepVariation(variation, 1)) : setPly((p) => clampPly(p + 1, maxPly)),
    first: () =>
      variation ? setVariation(stepVariation(variation, -variation.index)) : setPly(0),
    last: () =>
      variation ? setVariation(stepVariation(variation, variation.sans.length)) : setPly(maxPly),
    flip: () => setFlipped((f) => !f),
    escape: () => {
      setVariation(null);
      setRetry(null);
    },
  };
  useKeyboardNav(nav);

  useEffect(() => setRetry(null), [ply]); // moving to another move ends a retry

  const handleBoardMove = (from: string, to: string) => {
    if (retry) {
      const before = positions?.[ply - 1];
      const result = before ? judgeRetry(before, from, to) : null;
      if (!result) return false;
      setRetry({ result, revealed: false });
      return true;
    }
    const next = playMove(variation ?? startVariation(ply, fens[ply]), from, to);
    if (!next) return false;
    setVariation(next);
    return true;
  };

  const explore = (basePly: number, sans: string[], upTo: number) => {
    const v = fromSans(basePly, fens[basePly], sans, upTo);
    if (!v) return;
    setPly(basePly);
    setVariation(v);
  };

  const fen = retry ? (retry.result?.fenAfter ?? fens[ply - 1]) : variation ? currentFen(variation) : fens[ply];
  const lastUci = !variation && !retry && ply > 0 ? game.moves[ply - 1].uci : null;
  const lastMove: [string, string] | null = variation
    ? lastMoveSquares(variation)
    : lastUci
      ? [lastUci.slice(0, 2), lastUci.slice(2, 4)]
      : null;
  // Engine lines: never show more than the analysis actually contains.
  const maxLines = (analysis ?? preview)?.run.multipv ?? 1;
  const linesShown = Math.max(1, Math.min(linesChoice, maxLines));
  const arrows: ArrowSpec[] =
    !variation && !retry && showArrow && here
      ? here.lines.slice(0, linesShown).flatMap((ln, i) =>
          ln.move_uci
            ? [{ from: ln.move_uci.slice(0, 2), to: ln.move_uci.slice(2, 4), color: LINE_COLORS[i] }]
            : [],
        )
      : [];
  // Chess.com-style mark on the square the last move went to.
  const mark =
    !variation && lastUci && here?.classification
      ? { square: lastUci.slice(2, 4), cls: here.classification }
      : null;

  const retryMover = retry && fens[ply - 1]?.split(" ")[1] === "b" ? "black" : "white";
  const orientation = retry ? (flipped ? (retryMover === "white" ? "black" : "white") : retryMover) : flipped ? "black" : "white";
  const top = flipped ? "white" : "black";
  const bottom = flipped ? "black" : "white";
  const player = (c: "white" | "black") => (
    <PlayerBar
      color={c}
      name={c === "white" ? game.white : game.black}
      elo={c === "white" ? game.white_elo : game.black_elo}
      winner={game.result === (c === "white" ? "1-0" : "0-1")}
    />
  );

  const bestBefore = retry && ply > 0 ? positions?.[ply - 1] : undefined;
  const retryBanner = retry && (
    <div
      className="rounded border border-blue-300 bg-blue-50 p-2 text-sm text-blue-900 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-100"
      role="status"
      data-testid="retry-banner"
    >
      <p className="font-semibold">
        {retry.result
          ? retry.result.found
            ? "Found it"
            : retry.result.kind === "unlisted"
              ? "Not judged"
              : "Not quite"
          : `Find a better move than ${game.moves[ply - 1]?.san ?? "the one played"}`}
      </p>
      {retry.result ? <p className="mt-1">{retryMessage(retry.result)}</p> : <p className="mt-1">Play your move on the board, or type it below. It is checked against the engine lines already saved for this position.</p>}
      {!retry.result && <MoveInput fen={fens[ply - 1]} onMove={handleBoardMove} />}
      {retry.revealed && bestBefore?.best_move_san && (
        <p className="mt-1" data-testid="retry-answer">The engine preferred {bestBefore.best_move_san} ({bestBefore.pv_san.slice(0, 4).join(" ")}).</p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {retry.result && (
          <button type="button" onClick={() => setRetry({ result: null, revealed: false })} className="min-h-11 rounded bg-blue-700 px-3 text-xs font-semibold text-white hover:bg-blue-800">
            Try again
          </button>
        )}
        {!retry.revealed && (
          <button type="button" onClick={() => setRetry({ ...retry, revealed: true })} className="min-h-11 rounded border border-blue-700 px-3 text-xs font-semibold hover:bg-blue-100 dark:hover:bg-blue-900">
            Show the answer
          </button>
        )}
        <button type="button" onClick={() => setRetry(null)} className="min-h-11 rounded border border-blue-700 px-3 text-xs font-semibold hover:bg-blue-100 dark:hover:bg-blue-900">
          Back to the game (Esc)
        </button>
      </div>
    </div>
  );

  const variationBanner = variation && (
    <div
      className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      role="status"
      data-testid="variation-banner"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          Exploring a variation from {ply === 0 ? "the start" : label(ply)} — not saved
        </span>
        <button
          type="button"
          onClick={() => setVariation(null)}
          className="rounded min-h-11 bg-amber-700 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-800"
        >
          Return to game (Esc)
        </button>
      </div>
      {variation.sans.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {formatVariation(variation).map((m) => (
            <button
              key={m.at}
              type="button"
              onClick={() => setVariation({ ...variation, index: m.at })}
              aria-current={variation.index === m.at ? "true" : undefined}
              className={`rounded px-1.5 py-0.5 ${variation.index === m.at ? "bg-amber-700 text-white" : "bg-amber-100 dark:bg-amber-900"}`}
            >
              {m.text}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const movesPanel = (
    <MoveList
      moves={game.moves}
      startFen={game.start_fen}
      currentPly={ply}
      classes={classes}
      dimmed={!!variation}
      onSelect={selectPly}
    />
  );
  const graphPanel =
    positions && (analysis || preview) ? (
      <EvalGraph
        positions={positions}
        currentPly={ply}
        swings={analysis?.summary.swings ?? []}
        onSelect={selectPly}
        pending={analysis ? 0 : maxPly + 1 - evaluated}
      />
    ) : (
      <p className="text-sm text-slate-600 dark:text-slate-400">The evaluation graph appears once the game has been analyzed.</p>
    );
  const enginePanel = variation ? (
    <p className="text-sm text-slate-600 dark:text-slate-400">
      Engine evaluation is only available for positions of the game itself. Return to the game to see it again.
    </p>
  ) : here ? (
    <div className="space-y-3">
    <EnginePanel
      current={here}
      previous={ply > 0 ? (positions?.[ply - 1] ?? null) : null}
      onExplore={explore}
      shown={linesShown}
      maxLines={maxLines}
      onShownChange={setLinesChoice}
      onRetry={() => {
        setVariation(null);
        setRetry({ result: null, revealed: false });
      }}
    />
    {analysis && ply > 0 && <ExplainBox gameId={game.id} ply={ply} previous={positions?.[ply - 1] ?? null} onExplore={explore} />}
    </div>
  ) : preview ? (
    <p className="text-sm text-slate-600 dark:text-slate-400">
      This position has not been analyzed yet. Pick a move that already has an evaluation.
    </p>
  ) : (
    <p className="text-sm text-slate-600 dark:text-slate-400">Analyze the game to see engine evaluations and best moves.</p>
  );
  const previewBanner = preview && (
    <div
      role="status"
      data-testid="preview-banner"
      className="rounded border border-blue-300 bg-blue-50 p-2 text-sm text-blue-900 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-100"
    >
      <span className="font-semibold">Live preview, not final.</span> {evaluated} of {maxPly + 1} positions
      analyzed so far. Marks may still change as deeper results arrive; the summary and accuracy appear when
      the analysis finishes.
    </div>
  );
  const summaryPanel = analysis ? (
    <div className="space-y-4">
    <SummaryCard
      summary={analysis.summary}
      white={game.white}
      black={game.black}
      onSelectPly={selectPly}
      moveLabel={label}
    />
    <KeyMoments gameId={game.id} plies={analysis.summary.key_positions.map((k) => k.ply)} moveLabel={label} onSelectPly={selectPly} />
    </div>
  ) : (
    <p className="text-sm text-slate-600 dark:text-slate-400">The summary appears once the game has been analyzed.</p>
  );

  const tabs = [...BASE_TABS, ...(game.clocks ? [TIME_TAB] : []), NOTES_TAB];
  const notesPanel = <GameNotes game={game} ply={variation ? 0 : ply} moveLabel={label} />;
  const timePanel = game.clocks ? (
    <ClockPanel
      clocks={game.clocks}
      startFen={game.start_fen}
      classes={classes}
      white={game.white}
      black={game.black}
      currentPly={ply}
      onSelect={selectPly}
      moveLabel={label}
    />
  ) : null;

  const boardBlock = (
    <div className="space-y-2">
      {player(top)}
      <div className="flex gap-2">
        <EvalBar evaluation={variation || retry ? null : (here?.eval ?? null)} orientation={orientation} />
        <div className="min-w-0 flex-1">
          <Board
            fen={fen}
            orientation={orientation}
            lastMove={lastMove}
            arrows={arrows}
            mark={mark}
            onMove={handleBoardMove}
          />
        </div>
      </div>
      {player(bottom)}
      <NavControls
        onFirst={nav.first}
        onPrev={nav.prev}
        onNext={nav.next}
        onLast={nav.last}
        onFlip={nav.flip}
        canPrev={variation ? true : ply > 0}
        canNext={variation ? variation.index < variation.sans.length : ply < maxPly}
      />
      <div className="flex items-center justify-between text-sm text-slate-600 dark:text-slate-400">
        <span data-testid="current-move" aria-live="polite">
          {variation ? "Variation" : ply === 0 ? "Start position" : label(ply)}
        </span>
        {analysis && (
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={showArrow} onChange={(e) => setShowArrow(e.target.checked)} />
            Show engine arrows
          </label>
        )}
      </div>
      <p className="hidden text-xs text-slate-600 dark:text-slate-400 sm:block">
        Keyboard: ← → move · Home/End first/last · F flip board · Esc leave variation
      </p>
      {retryBanner}
      {variationBanner}
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-4">
      <div className="mb-3">
        <Link to="/" className="text-sm text-blue-600 underline dark:text-blue-400">
          ← All games
        </Link>
        <h1 className="mt-1 text-xl font-bold">
          {game.white} vs {game.black}
        </h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {game.result !== "*" && <>{resultText(game.result)} · </>}
          {resultDescription(game.result)} · {dateText(game.played_at)}
          {(game.opening_name ?? analysis?.summary.opening?.name) &&
            ` · ${game.opening_name ?? analysis?.summary.opening?.name}`}
          {game.time_control && ` · ${game.time_control}`}
          {" · "}
          {SOURCE_LABEL[game.source] ?? game.source}
          {" · "}
          <a
            href={gamePgnUrl(game.id)}
            download
            className="text-blue-600 underline dark:text-blue-400"
          >
            Download PGN
          </a>
          {analysis && (
            <>
              {" · "}
              <a
                href={gamePgnUrl(game.id, true)}
                download
                className="text-blue-600 underline dark:text-blue-400"
              >
                with analysis
              </a>
            </>
          )}
        </p>
      </div>

      <div className={wide ? "grid grid-cols-[minmax(0,1fr)_380px] gap-4" : "space-y-4"}>
        <div className="space-y-4">
          {boardBlock}
          {wide && <Card>{graphPanel}</Card>}
        </div>

        <div className="space-y-4">
          <Card>
            <AnalysisPanel game={game} job={job} analysis={analysis} />
          </Card>

          {wide ? (
            <>
              {previewBanner}
              {(analysis || preview) && <Card title="Engine">{enginePanel}</Card>}
              {analysis && <Card title="Summary">{summaryPanel}</Card>}
              {timePanel && <Card title="Time">{timePanel}</Card>}
              <Card title="Notes">{notesPanel}</Card>
              <Card title="Moves">{movesPanel}</Card>
            </>
          ) : (
            <Card>
              <div role="tablist" aria-label="Review sections" className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-700">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    role="tab"
                    id={`tab-${t.id}`}
                    aria-selected={tab === t.id}
                    aria-controls={`panel-${t.id}`}
                    onClick={() => setTab(t.id)}
                    className={`min-h-11 flex-1 border-b-2 px-2 text-sm font-medium ${
                      tab === t.id ? "border-blue-600 text-blue-700 dark:text-blue-400" : "border-transparent text-slate-600 dark:text-slate-400"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {previewBanner && <div className="mb-3">{previewBanner}</div>}
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                {tab === "moves" && movesPanel}
                {tab === "graph" && graphPanel}
                {tab === "engine" && enginePanel}
                {tab === "summary" && summaryPanel}
                {tab === "time" && timePanel}
                {tab === "notes" && notesPanel}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
