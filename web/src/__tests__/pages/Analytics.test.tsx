import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Analytics from "../../pages/Analytics";
import type { StatsResult } from "../../types";

const sampleStats: StatsResult = {
  summary: {
    total_runs: 15,
    completed: 10,
    failed: 3,
    in_progress: 2,
    success_rate: 0.77,
    failure_rate: 0.23,
    total_cost_usd: 4.56,
  },
  cost_breakdown: [
    { phase: "plan", total_cost: 1.0, avg_cost: 0.1, pct_of_total: 22 },
    { phase: "implement", total_cost: 2.5, avg_cost: 0.25, pct_of_total: 55 },
  ],
  failure_hotspots: [
    { phase: "implement", executions: 15, failures: 3, failure_rate: 0.2 },
  ],
  review_loop: {
    avg_review_rounds: 1.5,
    first_pass_approval_rate: 0.6,
    total_review_rounds: 20,
    total_fix_iterations: 8,
  },
  duration_stats: [
    { label: "plan", avg_duration_ms: 30000 },
    { label: "implement", avg_duration_ms: 120000 },
  ],
  recent_trend: [
    { run_id: "run-001", status: "completed", cost_usd: 0.3 },
    { run_id: "run-002", status: "failed", cost_usd: 0.15 },
  ],
  phase_detail: [],
  phase_filter: null,
  model_usage: [
    { model: "claude-sonnet-4-20250514", invocations: 30, total_cost: 3.0, avg_cost: 0.1 },
  ],
};

function renderAnalytics() {
  return render(
    <MemoryRouter>
      <Analytics />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Analytics page", () => {
  it("renders analytics with stats data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(sampleStats),
      })
    );

    renderAnalytics();

    await waitFor(() => {
      expect(screen.getByText("Analytics")).toBeDefined();
    });

    // Summary cards
    await waitFor(() => {
      expect(screen.getByText("15")).toBeDefined(); // total runs
      expect(screen.getByText("77%")).toBeDefined(); // success rate
      expect(screen.getByText("$4.56")).toBeDefined(); // total cost
      expect(screen.getByText("2")).toBeDefined(); // in progress
    });

    // Charts render
    expect(screen.getByTestId("cost-chart")).toBeDefined();
    expect(screen.getByTestId("phase-cost-chart")).toBeDefined();
    expect(screen.getByTestId("failure-chart")).toBeDefined();

    // Model usage table
    expect(screen.getByTestId("model-usage-table")).toBeDefined();
    expect(screen.getByText("claude-sonnet-4-20250514")).toBeDefined();

    // Duration stats table
    expect(screen.getByTestId("duration-stats-table")).toBeDefined();

    // Review loop summary
    expect(screen.getByTestId("review-loop-summary")).toBeDefined();
    expect(screen.getByText("1.5")).toBeDefined(); // avg review rounds
    expect(screen.getByText("60%")).toBeDefined(); // first-pass approval
  });

  it("shows error state when API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.resolve({}),
      })
    );

    renderAnalytics();

    await waitFor(() => {
      expect(screen.getByTestId("analytics-error")).toBeDefined();
    });
  });

  it("shows loading state initially", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise(() => {})) // never resolves
    );

    renderAnalytics();
    expect(screen.getByText(/loading analytics/i)).toBeDefined();
  });
});
