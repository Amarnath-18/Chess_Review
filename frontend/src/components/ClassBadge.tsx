import type { MoveClass } from "../api/types";
import { CLASS_META } from "../lib/quality";

export function ClassBadge({ cls }: { cls: MoveClass }) {
  const m = CLASS_META[cls];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold text-white ${m.bg}`}
    >
      {m.glyph && <span aria-hidden="true">{m.glyph}</span>}
      {m.label}
    </span>
  );
}
