import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatsPanel from "../../components/StatsPanel";
import type { RunSummary } from "../../types";

const summary: RunSummary = {
  total_runs: 10,
  completed: 8,
  failed: 2,
  in_progress: 0,
  success_rate: 80.0,
  failure_rate: 20.0,
  total_cost_usd: 5.25,
};

describe("StatsPanel", () => {
  it("renders total runs", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("renders success rate", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("renders total cost", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("$5.25")).toBeInTheDocument();
  });

  it("renders in-progress count", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("renders average cost per run", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("$0.53 avg/run")).toBeInTheDocument();
  });
});
