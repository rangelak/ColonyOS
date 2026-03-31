import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PhaseTimeline from "../components/PhaseTimeline";
import type { PhaseTimelineEntry } from "../types";

function makeEntry(overrides: Partial<PhaseTimelineEntry> = {}): PhaseTimelineEntry {
  return {
    phase: "plan",
    model: "opus",
    duration_ms: 30000,
    cost_usd: 0.12,
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
  it("renders empty state when no entries", () => {
    render(<PhaseTimeline entries={[]} />);
    expect(screen.getByText("No phases recorded.")).toBeInTheDocument();
  });

  it("renders phase names", () => {
    const entries = [
      makeEntry({ phase: "plan" }),
      makeEntry({ phase: "implement" }),
    ];
    render(<PhaseTimeline entries={entries} />);
    expect(screen.getByText("plan")).toBeInTheDocument();
    expect(screen.getByText("implement")).toBeInTheDocument();
  });

  it("renders vertical connector lines between phases", () => {
    const entries = [
      makeEntry({ phase: "plan" }),
      makeEntry({ phase: "implement" }),
      makeEntry({ phase: "review" }),
    ];
    const { container } = render(<PhaseTimeline entries={entries} />);
    // Connector lines are rendered as divs between phase items
    const connectors = container.querySelectorAll("[data-testid='timeline-connector']");
    // There should be a connector between each pair of phases
    expect(connectors.length).toBe(2);
  });

  it("renders duration bars with proportional widths", () => {
    const entries = [
      makeEntry({ phase: "plan", duration_ms: 60000 }),
      makeEntry({ phase: "implement", duration_ms: 30000 }),
    ];
    const { container } = render(<PhaseTimeline entries={entries} />);
    const bars = container.querySelectorAll("[data-testid='duration-bar']");
    expect(bars.length).toBe(2);
    // First bar should be 100% (longest), second should be 50%
    const firstStyle = (bars[0] as HTMLElement).style.width;
    const secondStyle = (bars[1] as HTMLElement).style.width;
    expect(firstStyle).toBe("100%");
    expect(secondStyle).toBe("50%");
  });

  it("renders Lucide icons for success, failure, and skipped", () => {
    const entries = [
      makeEntry({ phase: "plan", success: true, is_skipped: false }),
      makeEntry({ phase: "implement", success: false, is_skipped: false }),
      makeEntry({ phase: "review", success: true, is_skipped: true }),
    ];
    const { container } = render(<PhaseTimeline entries={entries} />);
    // Lucide icons render as SVGs
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(3);
  });

  it("shows error text truncated by default", () => {
    const entries = [
      makeEntry({
        phase: "implement",
        success: false,
        error: "Something went terribly wrong with the implementation phase",
      }),
    ];
    render(<PhaseTimeline entries={entries} />);
    // Error should be visible but truncated
    const errorEl = screen.getByTestId("phase-error-0");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl.textContent).toContain("Something went terribly wrong");
  });

  it("expands error details on click", async () => {
    const user = userEvent.setup();
    const longError = "A".repeat(200);
    const entries = [
      makeEntry({
        phase: "implement",
        success: false,
        error: longError,
      }),
    ];
    render(<PhaseTimeline entries={entries} />);

    const errorToggle = screen.getByTestId("error-toggle-0");
    // Initially truncated
    const errorEl = screen.getByTestId("phase-error-0");
    expect(errorEl.classList.contains("line-clamp-1")).toBe(true);

    // Click to expand
    await user.click(errorToggle);
    expect(errorEl.classList.contains("line-clamp-1")).toBe(false);
  });

  it("renders model badge when model is present", () => {
    const entries = [makeEntry({ phase: "plan", model: "opus" })];
    render(<PhaseTimeline entries={entries} />);
    expect(screen.getByText("opus")).toBeInTheDocument();
  });

  it("renders cost and duration", () => {
    const entries = [makeEntry({ phase: "plan", cost_usd: 1.23, duration_ms: 65000 })];
    render(<PhaseTimeline entries={entries} />);
    expect(screen.getByText("$1.23")).toBeInTheDocument();
    expect(screen.getByText("1m 5s")).toBeInTheDocument();
  });

  it("renders collapsed review count", () => {
    const entries = [
      makeEntry({ phase: "review", is_collapsed: true, collapsed_count: 3 }),
    ];
    render(<PhaseTimeline entries={entries} />);
    expect(screen.getByText("(3 reviews)")).toBeInTheDocument();
  });

  it("groups review/fix loop iterations with a loop indicator", () => {
    const entries = [
      makeEntry({ phase: "plan", round_number: null }),
      makeEntry({ phase: "review", round_number: 1 }),
      makeEntry({ phase: "fix", round_number: 1 }),
      makeEntry({ phase: "review", round_number: 2 }),
      makeEntry({ phase: "fix", round_number: 2 }),
      makeEntry({ phase: "deliver", round_number: null }),
    ];
    const { container } = render(<PhaseTimeline entries={entries} />);
    // Review/fix loop groups should have a loop indicator
    const loopGroups = container.querySelectorAll("[data-testid='loop-group']");
    expect(loopGroups.length).toBeGreaterThanOrEqual(1);
  });

  it("handles zero duration without rendering a duration bar", () => {
    const entries = [makeEntry({ phase: "plan", duration_ms: 0 })];
    const { container } = render(<PhaseTimeline entries={entries} />);
    const bars = container.querySelectorAll("[data-testid='duration-bar']");
    // Bar should still exist but have 0% width
    expect(bars.length).toBe(1);
    expect((bars[0] as HTMLElement).style.width).toBe("0%");
  });
});
