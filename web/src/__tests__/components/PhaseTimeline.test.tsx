import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PhaseTimeline from "../../components/PhaseTimeline";
import type { PhaseTimelineEntry } from "../../types";

function makeEntry(overrides: Partial<PhaseTimelineEntry> = {}): PhaseTimelineEntry {
  return {
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
    ...overrides,
  };
}

describe("PhaseTimeline", () => {
  it("renders empty message when no entries", () => {
    render(<PhaseTimeline entries={[]} />);
    expect(screen.getByText("No phases recorded.")).toBeInTheDocument();
  });

  it("renders phase name and model badge", () => {
    render(<PhaseTimeline entries={[makeEntry()]} />);
    expect(screen.getByText("plan")).toBeInTheDocument();
    expect(screen.getByText("sonnet")).toBeInTheDocument();
  });

  it("renders cost and duration", () => {
    render(<PhaseTimeline entries={[makeEntry({ cost_usd: 0.05, duration_ms: 5000 })]} />);
    expect(screen.getByText("$0.05")).toBeInTheDocument();
    expect(screen.getByText("5s")).toBeInTheDocument();
  });

  it("shows error message for failed phases", () => {
    render(
      <PhaseTimeline
        entries={[makeEntry({ success: false, error: "Budget exceeded" })]}
      />
    );
    expect(screen.getByText("Budget exceeded")).toBeInTheDocument();
  });

  it("shows collapsed count for collapsed entries", () => {
    render(
      <PhaseTimeline
        entries={[makeEntry({ is_collapsed: true, collapsed_count: 3 })]}
      />
    );
    expect(screen.getByText("(3 reviews)")).toBeInTheDocument();
  });
});
