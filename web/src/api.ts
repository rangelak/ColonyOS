/** API client for the ColonyOS dashboard backend. */

import type {
  RunLog,
  ShowResult,
  StatsResult,
  ConfigResult,
  QueueState,
  Persona,
  ArtifactResult,
  ProposalEntry,
  ReviewEntry,
} from "./types";

const BASE = "/api";

// Auth token storage key
const TOKEN_KEY = "colonyos_auth_token";

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(`${BASE}${url}`);
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}: ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

async function writeJSON<T>(
  method: "PUT" | "POST",
  url: string,
  body: unknown
): Promise<T> {
  const resp = await fetch(`${BASE}${url}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(detail.detail || `API error ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

// Read endpoints
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

export function fetchHealth(): Promise<{ status: string; version: string; write_enabled: string }> {
  return fetchJSON<{ status: string; version: string; write_enabled: string }>("/health");
}

// Write endpoints
export function updateConfig(config: Partial<ConfigResult>): Promise<ConfigResult> {
  return writeJSON<ConfigResult>("PUT", "/config", config);
}

export function updatePersonas(personas: Persona[]): Promise<ConfigResult> {
  return writeJSON<ConfigResult>("PUT", "/config/personas", personas);
}

export function launchRun(prompt: string): Promise<{ status: string; run_id: string }> {
  return writeJSON<{ status: string; run_id: string }>("POST", "/runs", { prompt });
}

export function fetchArtifact(path: string): Promise<ArtifactResult> {
  // Do not use encodeURIComponent here — the path contains forward slashes
  // that FastAPI's {path:path} parameter expects as literal slashes.
  return fetchJSON<ArtifactResult>(`/artifacts/${path}`);
}

export function fetchProposals(): Promise<ProposalEntry[]> {
  return fetchJSON<ProposalEntry[]>("/proposals");
}

export function fetchReviews(): Promise<ReviewEntry[]> {
  return fetchJSON<ReviewEntry[]>("/reviews");
}
