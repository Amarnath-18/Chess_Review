import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, api } from "./client";
import type { Job } from "./types";

const isActive = (j?: Job | null) => !!j && (j.status === "queued" || j.status === "running");

export const useGames = (page = 1, pageSize = 10) =>
  useQuery({ queryKey: ["games", page, pageSize], queryFn: () => api.listGames(page, pageSize) });

export const useGame = (id: string) =>
  useQuery({
    queryKey: ["game", id],
    queryFn: () => api.getGame(id),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });

export const useAnalysis = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api.getAnalysis(id),
    enabled,
    retry: false,
    staleTime: Infinity, // a completed review never changes; refetched explicitly on new runs
  });

/** Polls an active job once a second and refreshes game data when it finishes. */
export function useJobProgress(gameId: string, latest: Job | null | undefined) {
  const qc = useQueryClient();
  const active = isActive(latest);
  const job = useQuery({
    queryKey: ["job", latest?.id],
    queryFn: () => api.getJob(latest!.id),
    enabled: active,
    refetchInterval: (q) => (isActive(q.state.data ?? latest) ? 1000 : false),
    initialData: latest ?? undefined,
  });
  const status = job.data?.status;
  useEffect(() => {
    if (active && (status === "completed" || status === "failed")) {
      qc.invalidateQueries({ queryKey: ["game", gameId] });
      qc.invalidateQueries({ queryKey: ["analysis", gameId] });
      qc.invalidateQueries({ queryKey: ["games"] });
    }
  }, [active, status, gameId, qc]);
  return (active ? job.data : latest) ?? latest ?? null;
}

function useRefreshAfter(gameId: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["game", gameId] });
    qc.invalidateQueries({ queryKey: ["analysis", gameId] });
    qc.invalidateQueries({ queryKey: ["games"] });
  };
}

export function useStartAnalysis(gameId: string) {
  const refresh = useRefreshAfter(gameId);
  return useMutation({
    mutationFn: (p: { depth?: number; nodes?: number; multipv?: number }) =>
      api.startAnalysis(gameId, p),
    onSuccess: refresh,
  });
}

export function useRetryJob(gameId: string) {
  const refresh = useRefreshAfter(gameId);
  return useMutation({ mutationFn: (jobId: string) => api.retryJob(jobId), onSuccess: refresh });
}

export function useImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { text?: string; file?: File }) =>
      input.file ? api.importPgnFile(input.file) : api.importPgn(input.text ?? ""),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["games"] }),
  });
}

export function useDeleteGame() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteGame(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["games"] }),
  });
}
