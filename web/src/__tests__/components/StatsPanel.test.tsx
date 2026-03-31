import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatsPanel from "../../components/StatsPanel";
import type { RunSummary, ReviewLoopStats } from "../../types";

const summary: RunSummary = {
  total_runs: 10,
  completed: 8,
  failed: 2,
  in_progress: 0,
  success_rate: 80.0,
  failure_rate: 20.0,
  total_cost_usd: 5.25,
};

const reviewLoop: ReviewLoopStats = {
  avg_review_rounds: 1.5,
  first_pass_approval_rate: 0.6,
  total_review_rounds: 6,
  total_fix_iterations: 3,
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

  it("renders failure rate", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("20.0%")).toBeInTheDocument();
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

  it("renders avg cost per run card", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.getByText("$0.53")).toBeInTheDocument();
    expect(screen.getByText("Avg Cost / Run")).toBeInTheDocument();
  });

  it("renders review loop stats when provided", () => {
    render(<StatsPanel summary={summary} reviewLoop={reviewLoop} />);
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("First-Pass Approval")).toBeInTheDocument();
    expect(screen.getByText("1.5")).toBeInTheDocument();
    expect(screen.getByText("Avg Review Rounds")).toBeInTheDocument();
    expect(screen.getByText("3 fix iterations")).toBeInTheDocument();
  });

  it("does not render review loop stats when not provided", () => {
    render(<StatsPanel summary={summary} />);
    expect(screen.queryByText("First-Pass Approval")).not.toBeInTheDocument();
    expect(screen.queryByText("Avg Review Rounds")).not.toBeInTheDocument();
  });
});
