import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PhaseCostChart, FailureHotspotsChart } from "../components/PhaseBreakdownChart";
import type { PhaseCostRow, PhaseFailureRow } from "../types";

function makeCostRow(overrides: Partial<PhaseCostRow> = {}): PhaseCostRow {
  return {
    phase: "implement",
    total_cost: 1.5,
    avg_cost: 0.3,
    pct_of_total: 0.45,
    ...overrides,
  };
}

function makeFailureRow(overrides: Partial<PhaseFailureRow> = {}): PhaseFailureRow {
  return {
    phase: "implement",
    executions: 10,
    failures: 2,
    failure_rate: 0.2,
    ...overrides,
  };
}

describe("PhaseCostChart", () => {
  it("renders empty state when data is empty", () => {
    render(<PhaseCostChart data={[]} />);
    expect(screen.getByTestId("phase-cost-chart-empty")).toBeInTheDocument();
    expect(screen.getByText("No phase cost data available yet.")).toBeInTheDocument();
  });

  it("renders chart container when data is provided", () => {
    const data = [
      makeCostRow({ phase: "plan", total_cost: 0.5, avg_cost: 0.1 }),
      makeCostRow({ phase: "implement", total_cost: 1.5, avg_cost: 0.3 }),
      makeCostRow({ phase: "review", total_cost: 0.8, avg_cost: 0.16 }),
    ];
    render(<PhaseCostChart data={data} />);
    expect(screen.getByTestId("phase-cost-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("phase-cost-chart-empty")).not.toBeInTheDocument();
  });

  it("renders with a single phase", () => {
    const data = [makeCostRow({ phase: "plan" })];
    render(<PhaseCostChart data={data} />);
    expect(screen.getByTestId("phase-cost-chart")).toBeInTheDocument();
  });

  it("handles zero-cost phases", () => {
    const data = [makeCostRow({ phase: "plan", total_cost: 0, avg_cost: 0 })];
    render(<PhaseCostChart data={data} />);
    expect(screen.getByTestId("phase-cost-chart")).toBeInTheDocument();
  });
});

describe("FailureHotspotsChart", () => {
  it("renders empty state when data is empty", () => {
    render(<FailureHotspotsChart data={[]} />);
    expect(screen.getByTestId("failure-chart-empty")).toBeInTheDocument();
    expect(screen.getByText("No failure data available yet.")).toBeInTheDocument();
  });

  it("renders chart container when data is provided", () => {
    const data = [
      makeFailureRow({ phase: "implement", failures: 3, failure_rate: 0.3 }),
      makeFailureRow({ phase: "review", failures: 1, failure_rate: 0.1 }),
    ];
    render(<FailureHotspotsChart data={data} />);
    expect(screen.getByTestId("failure-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("failure-chart-empty")).not.toBeInTheDocument();
  });

  it("renders with a single phase", () => {
    const data = [makeFailureRow()];
    render(<FailureHotspotsChart data={data} />);
    expect(screen.getByTestId("failure-chart")).toBeInTheDocument();
  });

  it("handles zero-failure phases", () => {
    const data = [makeFailureRow({ failures: 0, failure_rate: 0 })];
    render(<FailureHotspotsChart data={data} />);
    expect(screen.getByTestId("failure-chart")).toBeInTheDocument();
  });

  it("handles 100% failure rate", () => {
    const data = [makeFailureRow({ executions: 5, failures: 5, failure_rate: 1.0 })];
    render(<FailureHotspotsChart data={data} />);
    expect(screen.getByTestId("failure-chart")).toBeInTheDocument();
  });
});
