import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import CostChart from "../components/CostChart";
import type { RecentRunEntry } from "../types";

function makeEntry(overrides: Partial<RecentRunEntry> = {}): RecentRunEntry {
  return {
    run_id: "abc12345-6789-0000-0000-000000000000",
    status: "completed",
    cost_usd: 0.15,
    ...overrides,
  };
}

describe("CostChart", () => {
  it("renders empty state when data is empty", () => {
    render(<CostChart data={[]} />);
    expect(screen.getByTestId("cost-chart-empty")).toBeInTheDocument();
    expect(screen.getByText("No cost data available yet.")).toBeInTheDocument();
  });

  it("renders chart container when data is provided", () => {
    const data = [
      makeEntry({ run_id: "run-aaaa-0000-0000-0000-000000000001", cost_usd: 0.1 }),
      makeEntry({ run_id: "run-bbbb-0000-0000-0000-000000000002", cost_usd: 0.25 }),
      makeEntry({ run_id: "run-cccc-0000-0000-0000-000000000003", cost_usd: 0.05 }),
    ];
    render(<CostChart data={data} />);
    expect(screen.getByTestId("cost-chart")).toBeInTheDocument();
    // Should NOT show empty state
    expect(screen.queryByTestId("cost-chart-empty")).not.toBeInTheDocument();
  });

  it("renders with a single data point", () => {
    const data = [makeEntry({ cost_usd: 0.42 })];
    render(<CostChart data={data} />);
    expect(screen.getByTestId("cost-chart")).toBeInTheDocument();
  });

  it("does not crash with zero-cost entries", () => {
    const data = [
      makeEntry({ cost_usd: 0 }),
      makeEntry({ run_id: "run-bbbb-0000-0000-0000-000000000002", cost_usd: 0 }),
    ];
    render(<CostChart data={data} />);
    expect(screen.getByTestId("cost-chart")).toBeInTheDocument();
  });
});
