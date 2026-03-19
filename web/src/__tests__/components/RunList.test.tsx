import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RunList from "../../components/RunList";
import type { RunLog } from "../../types";

function makeRun(overrides: Partial<RunLog> = {}): RunLog {
  return {
    run_id: "run-20260318_120000-abc123",
    prompt: "Add login feature",
    status: "completed",
    phases: [
      {
        phase: "plan",
        success: true,
        cost_usd: 0.05,
        duration_ms: 5000,
        session_id: "sess-1",
        model: "sonnet",
        error: null,
        artifacts: {},
      },
    ],
    total_cost_usd: 0.15,
    started_at: "2026-03-18T12:00:00+00:00",
    finished_at: "2026-03-18T12:01:00+00:00",
    branch_name: "colonyos/add-login",
    prd_rel: null,
    task_rel: null,
    source_issue: null,
    source_issue_url: null,
    ...overrides,
  };
}

describe("RunList", () => {
  it("shows empty state when no runs", () => {
    render(
      <MemoryRouter>
        <RunList runs={[]} />
      </MemoryRouter>
    );
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  it("renders run rows with correct data", () => {
    render(
      <MemoryRouter>
        <RunList runs={[makeRun()]} />
      </MemoryRouter>
    );
    expect(screen.getByText("run-20260318_120000-abc123")).toBeInTheDocument();
    expect(screen.getByText("Add login feature")).toBeInTheDocument();
    expect(screen.getByText("$0.15")).toBeInTheDocument();
  });

  it("links to run detail page", () => {
    render(
      <MemoryRouter>
        <RunList runs={[makeRun()]} />
      </MemoryRouter>
    );
    const link = screen.getByText("run-20260318_120000-abc123");
    expect(link.closest("a")).toHaveAttribute(
      "href",
      "/runs/run-20260318_120000-abc123"
    );
  });

  it("renders multiple runs", () => {
    const runs = [
      makeRun({ run_id: "run-1", prompt: "First" }),
      makeRun({ run_id: "run-2", prompt: "Second", status: "failed" }),
    ];
    render(
      <MemoryRouter>
        <RunList runs={runs} />
      </MemoryRouter>
    );
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });
});
