import { Link } from "react-router-dom";
import { useDeleteGame, useGames } from "../api/hooks";
import { Card } from "../components/Card";
import { CONFIRM_DELETE_GAME, GameListItem } from "../components/GameListItem";
import { ImportPanel } from "../components/ImportPanel";

function RecentGames() {
  const games = useGames(1, 10);
  const del = useDeleteGame();

  return (
    <Card title="Recent games">
      {games.isLoading && <p role="status" className="text-sm text-slate-500">Loading…</p>}
      {games.isError && (
        <p role="alert" className="text-sm text-red-600">
          Could not load your games: {(games.error as Error).message}
        </p>
      )}
      {games.data && games.data.items.length === 0 && (
        <p className="text-sm text-slate-500">
          No games yet. Paste or upload a PGN, or fetch games from Chess.com or Lichess, to get
          started. Your games are kept in this browser's session.
        </p>
      )}
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {games.data?.items.map((g) => (
          <GameListItem
            key={g.id}
            game={g}
            onDelete={(game) => window.confirm(CONFIRM_DELETE_GAME) && del.mutate(game.id)}
          />
        ))}
      </ul>
      {games.data && games.data.total > games.data.items.length && (
        <Link to="/games" className="mt-2 inline-block text-sm text-blue-600 underline dark:text-blue-400">
          View all {games.data.total} games →
        </Link>
      )}
    </Card>
  );
}

export default function HomePage() {
  return (
    <div className="mx-auto grid max-w-5xl grid-cols-[minmax(0,1fr)] gap-4 px-4 py-4 md:grid-cols-2">
      <ImportPanel />
      <RecentGames />
    </div>
  );
}
