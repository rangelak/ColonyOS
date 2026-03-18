/** API client for the ColonyOS dashboard backend. */

import type {
  RunLog,
  ShowResult,
  StatsResult,
  ConfigResult,
  QueueState,
} from "./types";

const BASE = "/api";

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(`${BASE}${url}`);
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}: ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export function fetchRuns(): Promise<RunLog[]> {
  return fetchJSON<RunLog[]>("/runs");
}

export function fetchRun(runId: string): Promise<ShowResult> {
  return fetchJSON<ShowResult>(`/runs/${encodeURIComponent(runId)}`);
}

export function fetchStats(): Promise<StatsResult> {
  return fetchJSON<StatsResult>("/stats");
}

export function fetchConfig(): Promise<ConfigResult> {
  return fetchJSON<ConfigResult>("/config");
}

export function fetchQueue(): Promise<QueueState | null> {
  return fetchJSON<QueueState | null>("/queue");
}

export function fetchHealth(): Promise<{ status: string; version: string }> {
  return fetchJSON<{ status: string; version: string }>("/health");
}
