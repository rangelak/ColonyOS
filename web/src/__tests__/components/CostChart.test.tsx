import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import CostChart from "../../components/CostChart";
import type { RecentRunEntry } from "../../types";

const sampleData: RecentRunEntry[] = [
  { run_id: "run-abc-001", status: "completed", cost_usd: 0.12 },
  { run_id: "run-abc-002", status: "completed", cost_usd: 0.25 },
  { run_id: "run-abc-003", status: "failed", cost_usd: 0.08 },
];

describe("CostChart", () => {
  it("renders the chart container with data", () => {
    render(<CostChart data={sampleData} />);
    expect(screen.getByTestId("cost-chart")).toBeDefined();
  });

  it("shows empty state when no data", () => {
    render(<CostChart data={[]} />);
    expect(screen.getByTestId("cost-chart-empty")).toBeDefined();
    expect(screen.getByText(/no cost data/i)).toBeDefined();
  });
});
