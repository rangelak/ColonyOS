import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchRuns,
  fetchRun,
  fetchStats,
  fetchConfig,
  fetchQueue,
  fetchHealth,
} from "../api";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(data),
  };
}

function errorResponse(status: number, statusText: string) {
  return {
    ok: false,
    status,
    statusText,
    json: () => Promise.resolve({ detail: statusText }),
  };
}

describe("fetchRuns", () => {
  it("fetches runs from /api/runs", async () => {
    const runs = [{ run_id: "run-1", status: "completed" }];
    mockFetch.mockResolvedValueOnce(okResponse(runs));

    const result = await fetchRuns();
    expect(result).toEqual(runs);
    expect(mockFetch).toHaveBeenCalledWith("/api/runs");
  });

  it("throws on API error", async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(500, "Internal Server Error"));

    await expect(fetchRuns()).rejects.toThrow("API error 500");
  });
});

describe("fetchRun", () => {
  it("fetches a single run with URL-encoded ID", async () => {
    const show = { header: { run_id: "run-1" }, timeline: [] };
    mockFetch.mockResolvedValueOnce(okResponse(show));

    const result = await fetchRun("run-1");
    expect(result).toEqual(show);
    expect(mockFetch).toHaveBeenCalledWith("/api/runs/run-1");
  });

  it("encodes special characters in run ID", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({}));

    await fetchRun("run with spaces");
    expect(mockFetch).toHaveBeenCalledWith("/api/runs/run%20with%20spaces");
  });
});

describe("fetchStats", () => {
  it("fetches stats from /api/stats", async () => {
    const stats = { summary: { total_runs: 5 } };
    mockFetch.mockResolvedValueOnce(okResponse(stats));

    const result = await fetchStats();
    expect(result).toEqual(stats);
    expect(mockFetch).toHaveBeenCalledWith("/api/stats");
  });
});

describe("fetchConfig", () => {
  it("fetches config from /api/config", async () => {
    const config = { model: "sonnet", personas: [] };
    mockFetch.mockResolvedValueOnce(okResponse(config));

    const result = await fetchConfig();
    expect(result).toEqual(config);
    expect(mockFetch).toHaveBeenCalledWith("/api/config");
  });
});

describe("fetchQueue", () => {
  it("fetches queue from /api/queue", async () => {
    const queue = { queue_id: "q-1", items: [] };
    mockFetch.mockResolvedValueOnce(okResponse(queue));

    const result = await fetchQueue();
    expect(result).toEqual(queue);
    expect(mockFetch).toHaveBeenCalledWith("/api/queue");
  });

  it("handles null queue", async () => {
    mockFetch.mockResolvedValueOnce(okResponse(null));

    const result = await fetchQueue();
    expect(result).toBeNull();
  });
});

describe("fetchHealth", () => {
  it("fetches health from /api/health", async () => {
    const health = { status: "ok", version: "1.0.0" };
    mockFetch.mockResolvedValueOnce(okResponse(health));

    const result = await fetchHealth();
    expect(result).toEqual(health);
    expect(mockFetch).toHaveBeenCalledWith("/api/health");
  });
});
