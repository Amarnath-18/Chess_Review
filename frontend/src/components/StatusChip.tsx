import type { AnalysisStatus } from "../api/types";

const META: Record<AnalysisStatus, { label: string; cls: string }> = {
  none: { label: "Not analyzed", cls: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  queued: { label: "Queued", cls: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100" },
  running: { label: "Analyzing…", cls: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100" },
  completed: { label: "Analyzed", cls: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100" },
  failed: { label: "Failed", cls: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100" },
};

export function StatusChip({ status }: { status: AnalysisStatus }) {
  const m = META[status];
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${m.cls}`}>{m.label}</span>;
}
