import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchRuns,
  fetchRun,
  fetchStats,
  fetchConfig,
  fetchQueue,
  fetchHealth,
  updateConfig,
  updatePersonas,
  launchRun,
  fetchArtifact,
  fetchProposals,
  fetchReviews,
  setAuthToken,
  clearAuthToken,
} from "../api";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  clearAuthToken();
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

describe("updateConfig", () => {
  it("sends PUT to /api/config with auth header", async () => {
    setAuthToken("test-token");
    mockFetch.mockResolvedValueOnce(okResponse({ model: "opus" }));

    await updateConfig({ model: "opus" });
    expect(mockFetch).toHaveBeenCalledWith("/api/config", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer test-token",
      },
      body: JSON.stringify({ model: "opus" }),
    });
  });

  it("throws on error with detail message", async () => {
    setAuthToken("test-token");
    mockFetch.mockResolvedValueOnce(errorResponse(400, "Invalid model"));

    await expect(updateConfig({ model: "invalid" })).rejects.toThrow("Invalid model");
  });
});

describe("updatePersonas", () => {
  it("sends PUT to /api/config/personas", async () => {
    setAuthToken("test-token");
    const personas = [{ role: "Dev", expertise: "Code", perspective: "quality", reviewer: true }];
    mockFetch.mockResolvedValueOnce(okResponse({ personas }));

    await updatePersonas(personas);
    expect(mockFetch).toHaveBeenCalledWith("/api/config/personas", expect.objectContaining({
      method: "PUT",
    }));
  });
});

describe("launchRun", () => {
  it("sends POST to /api/runs", async () => {
    setAuthToken("test-token");
    mockFetch.mockResolvedValueOnce(okResponse({ status: "launched" }));

    const result = await launchRun("Add login");
    expect(result.status).toBe("launched");
    expect(mockFetch).toHaveBeenCalledWith("/api/runs", expect.objectContaining({
      method: "POST",
    }));
  });
});

describe("fetchArtifact", () => {
  it("fetches artifact content", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ content: "# PRD", path: "cOS_prds/test.md" }));

    const result = await fetchArtifact("cOS_prds/test.md");
    expect(result.content).toBe("# PRD");
  });

  it("preserves forward slashes in the path (no encodeURIComponent)", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ content: "ok", path: "cOS_reviews/decisions/gate.md" }));

    await fetchArtifact("cOS_reviews/decisions/gate.md");
    // Slashes must be literal — FastAPI {path:path} expects them unencoded
    expect(mockFetch).toHaveBeenCalledWith("/api/artifacts/cOS_reviews/decisions/gate.md");
  });
});

describe("fetchProposals", () => {
  it("fetches proposals list", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([{ filename: "p.md", path: "cOS_proposals/p.md" }]));

    const result = await fetchProposals();
    expect(result).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith("/api/proposals");
  });
});

describe("fetchReviews", () => {
  it("fetches reviews list", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([{ filename: "r.md", path: "cOS_reviews/r.md" }]));

    const result = await fetchReviews();
    expect(result).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith("/api/reviews");
  });
});
