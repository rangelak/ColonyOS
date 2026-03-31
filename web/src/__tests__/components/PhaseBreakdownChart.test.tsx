import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PhaseCostChart, FailureHotspotsChart } from "../../components/PhaseBreakdownChart";
import type { PhaseCostRow, PhaseFailureRow } from "../../types";

const costData: PhaseCostRow[] = [
  { phase: "plan", total_cost: 0.50, avg_cost: 0.10, pct_of_total: 30 },
  { phase: "implement", total_cost: 1.20, avg_cost: 0.24, pct_of_total: 60 },
];

const failureData: PhaseFailureRow[] = [
  { phase: "plan", executions: 10, failures: 1, failure_rate: 0.1 },
  { phase: "implement", executions: 10, failures: 3, failure_rate: 0.3 },
];

describe("PhaseCostChart", () => {
  it("renders the chart container with data", () => {
    render(<PhaseCostChart data={costData} />);
    expect(screen.getByTestId("phase-cost-chart")).toBeDefined();
  });

  it("shows empty state when no data", () => {
    render(<PhaseCostChart data={[]} />);
    expect(screen.getByTestId("phase-cost-chart-empty")).toBeDefined();
    expect(screen.getByText(/no phase cost data/i)).toBeDefined();
  });
});

describe("FailureHotspotsChart", () => {
  it("renders the chart container with data", () => {
    render(<FailureHotspotsChart data={failureData} />);
    expect(screen.getByTestId("failure-chart")).toBeDefined();
  });

  it("shows empty state when no data", () => {
    render(<FailureHotspotsChart data={[]} />);
    expect(screen.getByTestId("failure-chart-empty")).toBeDefined();
    expect(screen.getByText(/no failure data/i)).toBeDefined();
  });
});
