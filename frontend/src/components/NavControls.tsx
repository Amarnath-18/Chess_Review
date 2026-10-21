interface Props {
  onFirst: () => void;
  onPrev: () => void;
  onNext: () => void;
  onLast: () => void;
  onFlip: () => void;
  canPrev: boolean;
  canNext: boolean;
}

const btn =
  "flex h-11 min-w-11 flex-1 items-center justify-center rounded border border-slate-300 bg-white text-lg font-semibold hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:hover:bg-slate-700";

export function NavControls({ onFirst, onPrev, onNext, onLast, onFlip, canPrev, canNext }: Props) {
  return (
    <div className="flex gap-2" role="group" aria-label="Move navigation">
      <button type="button" className={btn} onClick={onFirst} disabled={!canPrev} aria-label="First move" title="First (Home)">
        ⏮
      </button>
      <button type="button" className={btn} onClick={onPrev} disabled={!canPrev} aria-label="Previous move" title="Previous (←)">
        ◀
      </button>
      <button type="button" className={btn} onClick={onNext} disabled={!canNext} aria-label="Next move" title="Next (→)">
        ▶
      </button>
      <button type="button" className={btn} onClick={onLast} disabled={!canNext} aria-label="Last move" title="Last (End)">
        ⏭
      </button>
      <button type="button" className={btn} onClick={onFlip} aria-label="Flip board" title="Flip board (F)">
        ⇅
      </button>
    </div>
  );
}
