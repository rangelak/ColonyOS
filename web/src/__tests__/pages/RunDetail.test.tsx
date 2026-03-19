import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RunDetail from "../../pages/RunDetail";

vi.mock("../../api", () => ({
  fetchRun: vi.fn(),
}));

import { fetchRun } from "../../api";
const mockFetchRun = vi.mocked(fetchRun);

beforeEach(() => {
  vi.clearAllMocks();
});

const mockShowResult = {
  header: {
    run_id: "run-20260318_120000-abc123",
    status: "completed",
    branch_name: "colonyos/add-login",
    total_cost_usd: 0.15,
    started_at: "2026-03-18T12:00:00+00:00",
    finished_at: "2026-03-18T12:01:00+00:00",
    wall_clock_ms: 60000,
    prompt: "Add login feature",
    prompt_truncated: "Add login feature",
    source_issue_url: null,
    last_successful_phase: "implement",
    prd_rel: null,
    task_rel: null,
  },
  timeline: [
    {
      phase: "plan",
      model: "sonnet",
      duration_ms: 5000,
      cost_usd: 0.05,
      success: true,
      is_collapsed: false,
      collapsed_count: 0,
      round_number: null,
      session_id: "sess-1",
      error: null,
      is_skipped: false,
    },
  ],
  review_summary: null,
  has_decision: false,
  decision_success: false,
  has_ci_fix: false,
  ci_fix_attempts: 0,
  ci_fix_final_success: false,
  phase_filter: null,
  phase_detail: [],
};

function renderRunDetail(runId: string) {
  return render(
    <MemoryRouter initialEntries={[`/runs/${runId}`]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RunDetail", () => {
  it("shows loading state", () => {
    mockFetchRun.mockReturnValue(new Promise(() => {}));
    renderRunDetail("run-20260318_120000-abc123");
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders run details after fetch", async () => {
    mockFetchRun.mockResolvedValueOnce(mockShowResult);
    renderRunDetail("run-20260318_120000-abc123");

    await waitFor(() => {
      expect(screen.getByText("Add login feature")).toBeInTheDocument();
    });
    expect(screen.getByText("$0.15")).toBeInTheDocument();
    expect(screen.getByText("plan")).toBeInTheDocument();
  });

  it("shows error on fetch failure", async () => {
    mockFetchRun.mockRejectedValueOnce(new Error("Run not found"));
    renderRunDetail("run-nonexistent");

    await waitFor(() => {
      expect(screen.getByText(/Run not found/)).toBeInTheDocument();
    });
  });

  it("renders review summary when present", async () => {
    const withReview = {
      ...mockShowResult,
      review_summary: {
        review_rounds: 2,
        fix_iterations: 1,
        per_round_review_counts: [3, 3],
      },
      has_decision: true,
      decision_success: true,
    };
    mockFetchRun.mockResolvedValueOnce(withReview);
    renderRunDetail("run-20260318_120000-abc123");

    await waitFor(() => {
      expect(screen.getByText("Review Summary")).toBeInTheDocument();
    });
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });
});
