interface Props {
  color: "white" | "black";
  name: string;
  elo: number | null;
  winner: boolean;
}

export function PlayerBar({ color, name, elo, winner }: Props) {
  return (
    <div className="flex items-center gap-2 text-sm" data-testid={`player-${color}`}>
      <span
        className={`inline-block h-3 w-3 rounded-sm border border-slate-500 ${color === "white" ? "bg-white" : "bg-slate-800"}`}
        aria-hidden="true"
      />
      <span className="font-semibold">{name}</span>
      {elo && <span className="text-slate-500">{elo}</span>}
      <span className="sr-only">{color === "white" ? "playing White" : "playing Black"}</span>
      {winner && (
        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-semibold dark:bg-slate-700">Winner</span>
      )}
    </div>
  );
}
