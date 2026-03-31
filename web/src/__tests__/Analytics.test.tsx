import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Analytics from "../pages/Analytics";
import type { StatsResult } from "../types";

function makeStats(overrides: Partial<StatsResult> = {}): StatsResult {
  return {
    summary: {
      total_runs: 25,
      completed: 20,
      failed: 3,
      in_progress: 2,
      success_rate: 0.8,
      failure_rate: 0.12,
      total_cost_usd: 12.5,
    },
    cost_breakdown: [
      { phase: "plan", total_cost: 2.0, avg_cost: 0.08, pct_of_total: 0.16 },
      { phase: "implement", total_cost: 8.0, avg_cost: 0.32, pct_of_total: 0.64 },
    ],
    failure_hotspots: [
      { phase: "implement", executions: 25, failures: 3, failure_rate: 0.12 },
    ],
    review_loop: {
      avg_review_rounds: 1.5,
      first_pass_approval_rate: 0.6,
      total_review_rounds: 30,
      total_fix_iterations: 12,
    },
    duration_stats: [
      { label: "plan", avg_duration_ms: 45000 },
      { label: "implement", avg_duration_ms: 120000 },
    ],
    recent_trend: [
      { run_id: "run-aaaa", status: "completed", cost_usd: 0.5 },
      { run_id: "run-bbbb", status: "completed", cost_usd: 0.3 },
    ],
    phase_detail: [],
    phase_filter: null,
    model_usage: [
      { model: "opus", invocations: 50, total_cost: 10.0, avg_cost: 0.2 },
      { model: "sonnet", invocations: 30, total_cost: 2.5, avg_cost: 0.083 },
    ],
    ...overrides,
  };
}

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function okResponse(data: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

describe("Analytics", () => {
  it("shows loading state initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    render(<Analytics />);
    expect(screen.getByText("Loading analytics...")).toBeInTheDocument();
  });

  it("renders summary cards after data loads", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("analytics-summary")).toBeInTheDocument();
    });

    expect(screen.getByText("Total Runs")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("Success Rate")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    // "Total Cost" appears as both a summary card label and a table header
    expect(screen.getAllByText("Total Cost").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("$12.50")).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders cost chart with data", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-chart")).toBeInTheDocument();
    });
  });

  it("renders phase cost chart", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("phase-cost-chart")).toBeInTheDocument();
    });
  });

  it("renders failure hotspots chart", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("failure-chart")).toBeInTheDocument();
    });
  });

  it("renders model usage table", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("model-usage-table")).toBeInTheDocument();
    });

    expect(screen.getByText("opus")).toBeInTheDocument();
    expect(screen.getByText("sonnet")).toBeInTheDocument();
  });

  it("renders duration stats table", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("duration-stats-table")).toBeInTheDocument();
    });

    expect(screen.getByText("plan")).toBeInTheDocument();
    expect(screen.getByText("implement")).toBeInTheDocument();
  });

  it("renders review loop summary", async () => {
    const stats = makeStats();
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("review-loop-summary")).toBeInTheDocument();
    });

    expect(screen.getByText("Avg Review Rounds")).toBeInTheDocument();
    expect(screen.getByText("1.5")).toBeInTheDocument();
    expect(screen.getByText("First-Pass Approval")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("renders error state on fetch failure", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("analytics-error")).toBeInTheDocument();
    });

    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it("handles empty data arrays gracefully", async () => {
    const stats = makeStats({
      cost_breakdown: [],
      failure_hotspots: [],
      model_usage: [],
      duration_stats: [],
      recent_trend: [],
    });
    mockFetch.mockReturnValue(okResponse(stats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByTestId("analytics-summary")).toBeInTheDocument();
    });

    // Empty state messages should appear for each chart
    expect(screen.getByTestId("cost-chart-empty")).toBeInTheDocument();
    expect(screen.getByTestId("phase-cost-chart-empty")).toBeInTheDocument();
    expect(screen.getByTestId("failure-chart-empty")).toBeInTheDocument();
    expect(screen.getByTestId("model-usage-empty")).toBeInTheDocument();
    expect(screen.getByTestId("duration-stats-empty")).toBeInTheDocument();
  });

  it("uses success rate color coding correctly", async () => {
    // High success rate (>= 70%) should use emerald
    const highSuccessStats = makeStats({
      summary: {
        total_runs: 10,
        completed: 8,
        failed: 1,
        in_progress: 1,
        success_rate: 0.8,
        failure_rate: 0.1,
        total_cost_usd: 5.0,
      },
    });
    mockFetch.mockReturnValue(okResponse(highSuccessStats));

    const { unmount } = render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByText("80%")).toBeInTheDocument();
    });

    // The 80% value parent should have emerald color
    const successEl = screen.getByText("80%");
    expect(successEl.className).toContain("text-emerald-400");

    unmount();

    // Low success rate (< 70%) should use yellow
    const lowSuccessStats = makeStats({
      summary: {
        total_runs: 10,
        completed: 5,
        failed: 4,
        in_progress: 1,
        success_rate: 0.5,
        failure_rate: 0.4,
        total_cost_usd: 5.0,
      },
    });
    mockFetch.mockReturnValue(okResponse(lowSuccessStats));

    render(<Analytics />);

    await waitFor(() => {
      expect(screen.getByText("50%")).toBeInTheDocument();
    });

    const lowSuccessEl = screen.getByText("50%");
    expect(lowSuccessEl.className).toContain("text-yellow-400");
  });
});
