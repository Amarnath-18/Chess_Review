import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, gamePgnUrl } from "../api/client";
import { useAnalysis, useGame, useJobProgress } from "../api/hooks";
import type { Analysis, GameDetail, Job, MoveClass } from "../api/types";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { Board } from "../components/Board";
import { Card } from "../components/Card";
import { EnginePanel } from "../components/EnginePanel";
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
  return <Review key={gameQ.data.id} game={gameQ.data} job={job} analysis={analysisQ.data} />;
}

type Tab = "moves" | "graph" | "engine" | "summary";
const TABS: { id: Tab; label: string }[] = [
  { id: "moves", label: "Moves" },
  { id: "graph", label: "Graph" },
  { id: "engine", label: "Engine" },
  { id: "summary", label: "Summary" },
];

function Review({ game, job, analysis }: { game: GameDetail; job: Job | null; analysis: Analysis | undefined }) {
  useDocumentTitle(`${game.white} vs ${game.black}`);
  const [ply, setPly] = useState(0);
  const [variation, setVariation] = useState<Variation | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [showArrow, setShowArrow] = useState(true);
  const [linesChoice, setLinesChoice] = useState(3); // how many engine lines to display
  const [tab, setTab] = useState<Tab>("moves");
  const wide = useMediaQuery("(min-width: 1024px)");

  const maxPly = game.moves.length;
  const fens = useMemo(() => [game.start_fen, ...game.moves.map((m) => m.fen)], [game]);
  const positions = analysis?.positions;
  const here = positions?.[ply];
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
    escape: () => setVariation(null),
  };
  useKeyboardNav(nav);

  const handleBoardMove = (from: string, to: string) => {
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

  const fen = variation ? currentFen(variation) : fens[ply];
  const lastUci = !variation && ply > 0 ? game.moves[ply - 1].uci : null;
  const lastMove: [string, string] | null = variation
    ? lastMoveSquares(variation)
    : lastUci
      ? [lastUci.slice(0, 2), lastUci.slice(2, 4)]
      : null;
  // Engine lines: never show more than the analysis actually contains.
  const maxLines = analysis?.run.multipv ?? 1;
  const linesShown = Math.max(1, Math.min(linesChoice, maxLines));
  const arrows: ArrowSpec[] =
    !variation && showArrow && here
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

  const orientation = flipped ? "black" : "white";
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
    analysis && positions ? (
      <EvalGraph positions={positions} currentPly={ply} swings={analysis.summary.swings} onSelect={selectPly} />
    ) : (
      <p className="text-sm text-slate-600 dark:text-slate-400">The evaluation graph appears once the game has been analyzed.</p>
    );
  const enginePanel = variation ? (
    <p className="text-sm text-slate-600 dark:text-slate-400">
      Engine evaluation is only available for positions of the game itself. Return to the game to see it again.
    </p>
  ) : here ? (
    <EnginePanel
      current={here}
      previous={ply > 0 ? (positions?.[ply - 1] ?? null) : null}
      onExplore={explore}
      shown={linesShown}
      maxLines={maxLines}
      onShownChange={setLinesChoice}
    />
  ) : (
    <p className="text-sm text-slate-600 dark:text-slate-400">Analyze the game to see engine evaluations and best moves.</p>
  );
  const summaryPanel = analysis ? (
    <SummaryCard
      summary={analysis.summary}
      white={game.white}
      black={game.black}
      onSelectPly={selectPly}
      moveLabel={label}
    />
  ) : (
    <p className="text-sm text-slate-600 dark:text-slate-400">The summary appears once the game has been analyzed.</p>
  );

  const boardBlock = (
    <div className="space-y-2">
      {player(top)}
      <div className="flex gap-2">
        <EvalBar evaluation={variation ? null : (here?.eval ?? null)} orientation={orientation} />
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
          {game.opening_name && ` · ${game.opening_name}`}
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
              {analysis && <Card title="Engine">{enginePanel}</Card>}
              {analysis && <Card title="Summary">{summaryPanel}</Card>}
              <Card title="Moves">{movesPanel}</Card>
            </>
          ) : (
            <Card>
              <div role="tablist" aria-label="Review sections" className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-700">
                {TABS.map((t) => (
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
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                {tab === "moves" && movesPanel}
                {tab === "graph" && graphPanel}
                {tab === "engine" && enginePanel}
                {tab === "summary" && summaryPanel}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
