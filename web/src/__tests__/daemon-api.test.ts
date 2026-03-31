import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchDaemonHealth,
  pauseDaemon,
  resumeDaemon,
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

function okResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Service Unavailable",
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

describe("fetchDaemonHealth", () => {
  it("fetches health from /healthz", async () => {
    const health = {
      status: "healthy",
      heartbeat_age_seconds: 2.5,
      queue_depth: 3,
      daily_spend_usd: 1.5,
      daily_budget_remaining_usd: 8.5,
      circuit_breaker_active: false,
      paused: false,
      total_items_today: 5,
      consecutive_failures: 0,
    };
    mockFetch.mockResolvedValueOnce(okResponse(health));

    const result = await fetchDaemonHealth();
    expect(result).toEqual(health);
    expect(mockFetch).toHaveBeenCalledWith("/healthz");
  });

  it("returns health data even on 503 (degraded/stopped)", async () => {
    const health = {
      status: "stopped",
      heartbeat_age_seconds: null,
      queue_depth: 0,
      daily_spend_usd: 10.0,
      daily_budget_remaining_usd: 0.0,
      circuit_breaker_active: false,
      paused: false,
      total_items_today: 10,
      consecutive_failures: 5,
    };
    mockFetch.mockResolvedValueOnce(okResponse(health, 503));

    const result = await fetchDaemonHealth();
    expect(result).toEqual(health);
  });

  it("throws on non-503 error status", async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(404, "Not Found"));

    await expect(fetchDaemonHealth()).rejects.toThrow("API error 404");
  });
});

describe("pauseDaemon", () => {
  it("sends POST to /api/daemon/pause with auth header", async () => {
    setAuthToken("test-token");
    const health = { status: "degraded", paused: true };
    mockFetch.mockResolvedValueOnce(okResponse(health));

    const result = await pauseDaemon();
    expect(result).toEqual(health);
    expect(mockFetch).toHaveBeenCalledWith("/api/daemon/pause", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer test-token",
      },
      body: JSON.stringify({}),
    });
  });

  it("throws on auth error", async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(401, "Unauthorized"));

    await expect(pauseDaemon()).rejects.toThrow("Unauthorized");
  });
});

describe("resumeDaemon", () => {
  it("sends POST to /api/daemon/resume with auth header", async () => {
    setAuthToken("test-token");
    const health = { status: "healthy", paused: false };
    mockFetch.mockResolvedValueOnce(okResponse(health));

    const result = await resumeDaemon();
    expect(result).toEqual(health);
    expect(mockFetch).toHaveBeenCalledWith("/api/daemon/resume", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer test-token",
      },
      body: JSON.stringify({}),
    });
  });
});
