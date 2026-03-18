import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "../../pages/Dashboard";

vi.mock("../../api", () => ({
  fetchRuns: vi.fn(),
  fetchStats: vi.fn(),
  fetchHealth: vi.fn(),
}));

import { fetchRuns, fetchStats, fetchHealth } from "../../api";
const mockFetchRuns = vi.mocked(fetchRuns);
const mockFetchStats = vi.mocked(fetchStats);
const mockFetchHealth = vi.mocked(fetchHealth);

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchHealth.mockResolvedValue({ status: "ok", version: "1.0", write_enabled: "false" });
});

const mockStats = {
  summary: {
    total_runs: 5,
    completed: 4,
    failed: 1,
    in_progress: 0,
    success_rate: 80.0,
    failure_rate: 20.0,
    total_cost_usd: 2.5,
  },
  cost_breakdown: [],
  failure_hotspots: [],
  review_loop: {
    avg_review_rounds: 1.5,
    first_pass_approval_rate: 0.6,
    total_review_rounds: 6,
    total_fix_iterations: 3,
  },
  duration_stats: [],
  recent_trend: [],
  phase_detail: [],
  phase_filter: null,
  model_usage: [],
};

const mockRuns = [
  {
    run_id: "run-1",
    prompt: "Add feature",
    status: "completed" as const,
    phases: [],
    total_cost_usd: 0.5,
    started_at: "2026-03-18T12:00:00+00:00",
    finished_at: "2026-03-18T12:01:00+00:00",
    branch_name: null,
    prd_rel: null,
    task_rel: null,
    source_issue: null,
    source_issue_url: null,
  },
];

describe("Dashboard", () => {
  it("renders loading state initially", () => {
    mockFetchRuns.mockReturnValue(new Promise(() => {}));
    mockFetchStats.mockReturnValue(new Promise(() => {}));

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders stats and runs after fetch", async () => {
    mockFetchRuns.mockResolvedValueOnce(mockRuns);
    mockFetchStats.mockResolvedValueOnce(mockStats);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument();
    });
    expect(screen.getByText("Add feature")).toBeInTheDocument();
  });

  it("shows error on fetch failure", async () => {
    mockFetchRuns.mockRejectedValueOnce(new Error("Network error"));
    mockFetchStats.mockRejectedValueOnce(new Error("Network error"));

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Network error/)).toBeInTheDocument();
    });
  });
});
