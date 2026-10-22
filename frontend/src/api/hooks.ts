import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, api } from "./client";
import type { BatchRequest, ExternalSource, GameDetail, GameQuery, GameUpdate, Job, SettingsPatch } from "./types";

const isActive = (j?: Job | null) => !!j && (j.status === "queued" || j.status === "running");

export const useGames = (page = 1, pageSize = 10, query: GameQuery = {}) =>
  useQuery({
    queryKey: ["games", page, pageSize, query],
    queryFn: () => api.listGames(page, pageSize, query),
    placeholderData: keepPreviousData,
  });

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

/** Positions evaluated so far by a running analysis, refreshed every two seconds. */
export const usePartialAnalysis = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["analysis-partial", id],
    queryFn: () => api.getPartialAnalysis(id),
    enabled,
    retry: false,
    refetchInterval: enabled ? 2000 : false,
    staleTime: 0,
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

export function usePreviewGames() {
  return useMutation({
    mutationFn: (p: { source: ExternalSource; username: string; maxGames: number }) =>
      api.previewGames(p.source, p.username, p.maxGames),
  });
}

export function useCommitGames() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: { source: ExternalSource; username: string; ids: string[] }) =>
      api.commitGames(p.source, p.username, p.ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["games"] }),
  });
}

export function useImportLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: { url: string; usernameHint?: string }) =>
      api.importFromLink(p.url, p.usernameHint),
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

/** The user's saved preferences. Pages fall back to sensible defaults while this loads or fails. */
export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: api.getSettings, staleTime: 60_000, retry: 1 });

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SettingsPatch) => api.updateSettings(patch),
    onSuccess: (data) => qc.setQueryData(["settings"], data),
  });
}

export function useDeleteAllGames() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteAllGames(),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useDeleteEverything() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteEverything(),
    onSuccess: () => qc.clear(),
  });
}

/** Rough time for analysing a game with these settings. Failing quietly is fine: it is only a hint. */
export const useEstimate = (gameId: string, depth: number, lines: number, enabled: boolean) =>
  useQuery({
    queryKey: ["estimate", gameId, depth, lines],
    queryFn: () => api.getEstimate(gameId, depth, lines),
    enabled,
    retry: false,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });

// ---- notes, tags and favourites ----------------------------------------------------------

/** Saves the owner's notes. The server's reply is the new game, so the page updates at once. */
export function useGameNotes(gameId: string) {
  const qc = useQueryClient();
  const apply = (game: GameDetail) => {
    qc.setQueryData(["game", gameId], game);
    qc.invalidateQueries({ queryKey: ["games"] }); // list rows show the star, tags and note mark
  };
  return {
    update: useMutation({ mutationFn: (patch: GameUpdate) => api.updateGame(gameId, patch), onSuccess: apply }),
    moveNote: useMutation({
      mutationFn: (p: { ply: number; text: string }) => api.putMoveNote(gameId, p.ply, p.text),
      onSuccess: apply,
    }),
  };
}

// ---- analyze-all ---------------------------------------------------------------------------

/** The running batch (polled every two seconds) or the latest finished one; null if never used. */
export function useLatestBatch() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["batch-latest"],
    queryFn: api.latestBatch,
    select: (b) => (b && b.counts ? b : null), // ignore anything that is not a batch
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
  const status = q.data?.status;
  useEffect(() => {
    // games finish while it runs (and when it ends): keep the list, its status chips and the
    // "games without a review" estimate (cached under ["games", ...]) fresh
    if (status) qc.invalidateQueries({ queryKey: ["games"] });
  }, [status, q.data?.counts?.done, qc]);
  return q;
}

export const useBatchEstimate = (body: BatchRequest, enabled: boolean) =>
  useQuery({
    queryKey: ["games", "batch-estimate", body],
    queryFn: () => api.estimateBatch(body),
    enabled,
    retry: false,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });

export function useStartBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BatchRequest) => api.startBatch(body),
    onSuccess: (batch) => {
      qc.setQueryData(["batch-latest"], batch);
      qc.invalidateQueries({ queryKey: ["games"] });
    },
  });
}

export function useCancelBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelBatch(id),
    onSuccess: (batch) => {
      qc.setQueryData(["batch-latest"], batch);
      qc.invalidateQueries({ queryKey: ["games"] });
    },
  });
}

// ---- remembered accounts ---------------------------------------------------------------------

export const useSources = () => useQuery({ queryKey: ["sources"], queryFn: api.listSources, retry: 1 });

export function useRememberSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: { source: ExternalSource; username: string }) => api.rememberSource(p.source, p.username),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useForgetSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.forgetSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useCheckSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.checkSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

// ---- training and statistics -------------------------------------------------------------------

/** What is due, and the next puzzle. Fetching it also mines newly analyzed games for puzzles. */
export const useTrain = () =>
  useQuery({ queryKey: ["train"], queryFn: api.getTrain, staleTime: 0, refetchOnWindowFocus: false, retry: 1 });

export function useAnswerPuzzle() {
  return useMutation({ mutationFn: (p: { id: string; uci: string }) => api.answerPuzzle(p.id, p.uci) });
}

export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: api.getStats, retry: 1 });

// ---- private server ------------------------------------------------------------------------------

export const useAccess = () => useQuery({ queryKey: ["access"], queryFn: api.getAccess, retry: false, staleTime: 30_000 });

export function useUnlock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.unlock(code),
    onSuccess: (status) => {
      qc.setQueryData(["access"], status);
      qc.invalidateQueries(); // everything fetched while locked is stale
    },
  });
}

// ---- AI explanations ---------------------------------------------------------------------------

export const useExplanations = (gameId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["explanations", gameId],
    queryFn: () => api.listExplanations(gameId),
    enabled,
    retry: false,
    staleTime: 30_000,
  });

export function useExplain(gameId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ply: number) => api.explainMove(gameId, ply),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["explanations", gameId] }),
  });
}
