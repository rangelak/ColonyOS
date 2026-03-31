import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "../../pages/Dashboard";

vi.mock("../../api", () => ({
  fetchRuns: vi.fn(),
  fetchStats: vi.fn(),
  fetchHealth: vi.fn(),
  fetchDaemonHealth: vi.fn(),
  fetchQueue: vi.fn(),
}));

import { fetchRuns, fetchStats, fetchHealth, fetchDaemonHealth, fetchQueue } from "../../api";
const mockFetchRuns = vi.mocked(fetchRuns);
const mockFetchStats = vi.mocked(fetchStats);
const mockFetchHealth = vi.mocked(fetchHealth);
const mockFetchDaemonHealth = vi.mocked(fetchDaemonHealth);
const mockFetchQueue = vi.mocked(fetchQueue);

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchHealth.mockResolvedValue({ status: "ok", version: "1.0", write_enabled: "false" });
  mockFetchDaemonHealth.mockRejectedValue(new Error("Not available"));
  mockFetchQueue.mockResolvedValue(null);
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
    source_type: "prompt",
    pr_url: null,
  },
];

const mockDaemonHealth = {
  status: "healthy" as const,
  heartbeat_age_seconds: 5,
  queue_depth: 3,
  daily_spend_usd: 1.5,
  daily_budget_remaining_usd: 8.5,
  circuit_breaker_active: false,
  paused: false,
  total_items_today: 7,
  consecutive_failures: 0,
};

const mockQueueState = {
  queue_id: "q-1",
  items: [
    {
      id: "item-1",
      source_type: "issue",
      source_value: "Fix the bug",
      status: "pending",
      added_at: "2026-03-18T12:00:00+00:00",
      run_id: null,
      cost_usd: 0,
      duration_ms: 0,
      pr_url: null,
      error: null,
      issue_title: "Bug report",
      priority: 1,
      demand_count: 2,
      urgency_score: 5,
      summary: null,
      notification_channel: null,
      related_item_ids: [],
      merged_sources: [],
    },
    {
      id: "item-2",
      source_type: "prompt",
      source_value: "Add tests",
      status: "running",
      added_at: "2026-03-18T11:00:00+00:00",
      run_id: "run-2",
      cost_usd: 0.3,
      duration_ms: 30000,
      pr_url: null,
      error: null,
      issue_title: null,
      priority: 2,
      demand_count: 1,
      urgency_score: 3,
      summary: null,
      notification_channel: null,
      related_item_ids: [],
      merged_sources: [],
    },
  ],
  aggregate_cost_usd: 0.3,
  start_time_iso: "2026-03-18T10:00:00+00:00",
  status: "active",
};

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

  it("renders daemon health summary when available", async () => {
    mockFetchRuns.mockResolvedValueOnce(mockRuns);
    mockFetchStats.mockResolvedValueOnce(mockStats);
    mockFetchDaemonHealth.mockResolvedValueOnce(mockDaemonHealth);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Daemon Health")).toBeInTheDocument();
    });
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText(/\$1\.50/)).toBeInTheDocument();
  });

  it("renders queue summary when queue data available", async () => {
    mockFetchRuns.mockResolvedValueOnce(mockRuns);
    mockFetchStats.mockResolvedValueOnce(mockStats);
    mockFetchQueue.mockResolvedValueOnce(mockQueueState);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Queue")).toBeInTheDocument();
    });
    expect(screen.getByText(/1 pending/)).toBeInTheDocument();
    expect(screen.getByText(/1 running/)).toBeInTheDocument();
  });

  it("renders enriched run list with source type", async () => {
    mockFetchRuns.mockResolvedValueOnce(mockRuns);
    mockFetchStats.mockResolvedValueOnce(mockStats);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Add feature")).toBeInTheDocument();
    });
    // Source type badge should be visible
    expect(screen.getAllByText("Prompt").length).toBeGreaterThanOrEqual(1);
  });
});
