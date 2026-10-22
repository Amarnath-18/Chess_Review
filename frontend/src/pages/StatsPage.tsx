import { Link } from "react-router-dom";
import { useStats } from "../api/hooks";
import type { OpeningStat, StatBucket, Stats } from "../api/types";
import { Card } from "../components/Card";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const muted = "text-slate-600 dark:text-slate-400";
const dim = "text-slate-500 dark:text-slate-400"; // sample too small: shown quieter, and also labelled

function TooFew({ what }: { what: string }) {
  return <span className="ml-1 rounded bg-slate-200 px-1 text-[11px] font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">too few {what}</span>;
}

function BucketTable({ title, rows, stats }: { title: string; rows: StatBucket[]; stats: Stats }) {
  if (rows.length === 0) return null;
  return (
    <Card title={title}>
      <table className="w-full text-sm">
        <thead>
          <tr className={`text-left text-xs ${muted}`}>
            <th scope="col" className="py-1 font-medium">Group</th>
            <th scope="col" className="py-1 text-right font-medium">Moves</th>
            <th scope="col" className="py-1 text-right font-medium">Mistakes + blunders per 100 moves</th>
            <th scope="col" className="hidden py-1 text-right font-medium sm:table-cell">?! / ? / ??</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.key} className={`border-t border-slate-200 dark:border-slate-800 ${b.reliable ? "" : dim}`} data-testid={`bucket-${b.key}`}>
              <th scope="row" className="py-1 text-left font-normal">
                {b.label}
                {!b.reliable && <TooFew what="moves to conclude" />}
              </th>
              <td className="py-1 text-right tabular-nums">{b.moves}</td>
              <td className="py-1 text-right tabular-nums">{b.serious_per_100 ?? "–"}</td>
              <td className="hidden py-1 text-right tabular-nums sm:table-cell">
                {b.inaccuracies} / {b.mistakes} / {b.blunders}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={`mt-2 text-xs ${muted}`}>
        Groups with fewer than {stats.min_moves} moves are greyed and labelled: that is too little to say anything about.
      </p>
    </Card>
  );
}

function OpeningTable({ rows, stats }: { rows: OpeningStat[]; stats: Stats }) {
  if (rows.length === 0) return null;
  return (
    <Card title="Openings you played">
      <table className="w-full text-sm">
        <thead>
          <tr className={`text-left text-xs ${muted}`}>
            <th scope="col" className="py-1 font-medium">Opening</th>
            <th scope="col" className="py-1 text-right font-medium">Games</th>
            <th scope="col" className="py-1 text-right font-medium">W / D / L</th>
            <th scope="col" className="py-1 text-right font-medium">Accuracy</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.name} className={`border-t border-slate-200 dark:border-slate-800 ${o.reliable ? "" : dim}`} data-testid="opening-row">
              <th scope="row" className="py-1 text-left font-normal">
                {o.name}
                {!o.reliable && <TooFew what="games" />}
              </th>
              <td className="py-1 text-right tabular-nums">{o.games}</td>
              <td className="py-1 text-right tabular-nums">
                {o.wins} / {o.draws} / {o.losses}
              </td>
              <td className="py-1 text-right tabular-nums">{o.accuracy != null ? `${o.accuracy}%` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={`mt-2 text-xs ${muted}`}>
        Openings with fewer than {stats.min_games} games are greyed: their results say little. Names come from the open
        Lichess opening list.
      </p>
    </Card>
  );
}

const W = 600;
const H = 120;

/** Accuracy of each analyzed game over time (this app's own number, 0-100). */
function Trend({ points }: { points: Stats["trend"] }) {
  const usable = points.filter((p) => p.accuracy != null);
  if (usable.length < 2) {
    return <p className={`text-sm ${muted}`}>The accuracy trend appears once you have two analyzed games.</p>;
  }
  const xy = usable.map((p, i) => ({
    x: (i / (usable.length - 1)) * W,
    y: H - ((p.accuracy as number) / 100) * H,
  }));
  const avg = usable.reduce((s, p) => s + (p.accuracy as number), 0) / usable.length;
  const first = usable[0].accuracy as number;
  const last = usable[usable.length - 1].accuracy as number;
  return (
    <figure className="m-0" data-testid="trend">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full rounded border border-slate-300 bg-slate-700 dark:border-slate-600"
        role="img"
        aria-label={`Accuracy per game, oldest to newest: from ${first.toFixed(0)}% to ${last.toFixed(0)}%, average ${avg.toFixed(0)}%`}
      >
        <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="stroke-slate-500" strokeDasharray="4 4" />
        <path d={xy.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")} className="fill-none stroke-white" strokeWidth={2} />
        {xy.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={3} className="fill-amber-300" />
        ))}
      </svg>
      <figcaption className={`mt-1 text-xs ${muted}`}>
        {usable.length} games, oldest to newest. Average {avg.toFixed(1)}%; first {first.toFixed(1)}%, latest {last.toFixed(1)}%.
        Accuracy is this app's own measure, higher is better.
      </figcaption>
    </figure>
  );
}

/** What your analyzed games say about how you play. Honest about small samples. */
export default function StatsPage() {
  useDocumentTitle("Your statistics");
  const q = useStats();
  const s = q.data;

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-4">
      <h1 className="text-xl font-bold">Your statistics</h1>
      {q.isLoading && <p role="status" className={`text-sm ${muted}`}>Loading…</p>}
      {q.isError && (
        <p role="alert" className="text-sm text-red-600">
          Could not load your statistics: {(q.error as Error).message}
        </p>
      )}
      {s?.needs_names && (
        <Card>
          <p className="text-sm">
            Statistics are about <em>you</em>, so the app needs to know which player you are. Add your name (as it
            appears in your games) in{" "}
            <Link className="text-blue-600 underline dark:text-blue-400" to="/settings">
              Settings
            </Link>
            , or remember your Chess.com / Lichess account on the home page.
          </p>
        </Card>
      )}
      {s && !s.needs_names && (
        <>
          <Card>
            <p className="text-sm" data-testid="stats-basis">
              Based on <strong>{s.games_included}</strong> analyzed game{s.games_included === 1 ? "" : "s"} where you could be
              identified, and <strong>{s.overall.moves}</strong> of your moves.
              {s.games_unidentified > 0 &&
                ` ${s.games_unidentified} analyzed game${s.games_unidentified === 1 ? " was" : "s were"} left out because neither player (or both) matches your names.`}
            </p>
            {s.games_included === 0 && (
              <p className={`mt-2 text-sm ${muted}`}>
                Nothing to show yet. Analyze some of your games first (the Games page can analyze them all).
              </p>
            )}
            {s.highlights.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm" data-testid="highlights">
                {s.highlights.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            )}
            {s.games_included > 0 && s.highlights.length === 0 && (
              <p className={`mt-2 text-sm ${muted}`}>
                No clear weak spot stands out yet. With few games or moves, differences are mostly chance, so nothing
                is called a weakness until there is enough data.
              </p>
            )}
          </Card>
          {s.games_included > 0 && (
            <>
              <Card title="Accuracy over time">
                <Trend points={s.trend} />
              </Card>
              <BucketTable title="By phase of the game" rows={s.by_phase} stats={s} />
              <BucketTable title="By colour" rows={s.by_color} stats={s} />
              <BucketTable title="By time control" rows={s.by_time_control} stats={s} />
              <OpeningTable rows={s.openings} stats={s} />
            </>
          )}
        </>
      )}
    </div>
  );
}
