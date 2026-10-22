import { Link } from "react-router-dom";
import { gamePgnUrl } from "../api/client";
import type { GameSummary } from "../api/types";
import { dateText, gameTitle, resultText, SOURCE_LABEL } from "../lib/format";
import { StatusChip } from "./StatusChip";

const action =
  "inline-flex min-h-11 items-center rounded px-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800";

/** One game in a list: opens the review, downloads its PGN, or deletes it. */
export function GameListItem({
  game,
  onDelete,
}: {
  game: GameSummary;
  onDelete: (game: GameSummary) => void;
}) {
  return (
    <li className="flex min-w-0 flex-col gap-1 py-2 sm:flex-row sm:items-center sm:gap-2">
      <Link
        to={`/games/${game.id}`}
        className="min-w-0 flex-1 rounded px-1 py-1 hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <div className="truncate font-medium">{gameTitle(game)}</div>
        <div className="truncate text-xs text-slate-600 dark:text-slate-400">
          {resultText(game.result)} · {dateText(game.played_at)} ·{" "}
          {SOURCE_LABEL[game.source] ?? game.source}
          {game.opening_name ? ` · ${game.opening_name}` : ""}
        </div>
      </Link>
      {(game.favorite || game.has_note || (game.tags?.length ?? 0) > 0) && (
        <ul className="flex min-w-0 shrink-0 flex-wrap items-center gap-1 px-1 text-xs" aria-label="Your marks">
          {game.favorite && (
            <li title="Favourite" className="font-semibold text-amber-700 dark:text-amber-400">
              <span aria-hidden="true">★</span>
              <span className="sr-only">Favourite</span>
            </li>
          )}
          {game.has_note && <li className="text-slate-600 dark:text-slate-400">Note</li>}
          {game.tags?.map((t) => (
            <li key={t} className="rounded-full bg-slate-200 px-2 py-0.5 dark:bg-slate-700">
              {t}
            </li>
          ))}
        </ul>
      )}
      <div className="flex shrink-0 items-center gap-1">
        <StatusChip status={game.analysis_status} />
        <a
          href={gamePgnUrl(game.id)}
          download
          aria-label={`Download PGN of ${gameTitle(game)}`}
          className={action}
        >
          PGN
        </a>
        <button
          type="button"
          aria-label={`Delete ${gameTitle(game)}`}
          onClick={() => onDelete(game)}
          className={`${action} hover:bg-red-100 hover:text-red-700 dark:hover:bg-red-950`}
        >
          Delete
        </button>
      </div>
    </li>
  );
}

export const CONFIRM_DELETE_GAME = "Delete this game and its analysis? This cannot be undone.";
