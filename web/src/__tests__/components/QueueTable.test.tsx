import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import QueueTable from "../../components/QueueTable";
import type { QueueItem } from "../../types";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    source_type: "issue",
    source_value: "Fix the login bug",
    status: "pending",
    added_at: "2026-03-30T12:00:00Z",
    run_id: null,
    cost_usd: 0,
    duration_ms: 0,
    pr_url: null,
    error: null,
    issue_title: null,
    priority: 50,
    demand_count: 1,
    urgency_score: 0.5,
    summary: null,
    notification_channel: null,
    related_item_ids: [],
    merged_sources: [],
    ...overrides,
  };
}

function renderTable(items: QueueItem[]) {
  return render(
    <MemoryRouter>
      <QueueTable items={items} />
    </MemoryRouter>
  );
}

describe("QueueTable", () => {
  it("renders a table with queue items", () => {
    renderTable([makeItem(), makeItem({ id: "item-2", source_value: "Update docs" })]);
    expect(screen.getByText(/Fix the login bug/)).toBeDefined();
    expect(screen.getByText(/Update docs/)).toBeDefined();
  });

  it("shows status badges with correct styling", () => {
    renderTable([
      makeItem({ status: "pending" }),
      makeItem({ id: "item-2", status: "running" }),
      makeItem({ id: "item-3", status: "completed" }),
      makeItem({ id: "item-4", status: "failed" }),
    ]);
    const badges = screen.getAllByTestId("queue-status-badge");
    expect(badges).toHaveLength(4);
    expect(badges[0].textContent).toContain("pending");
    expect(badges[1].textContent).toContain("running");
    expect(badges[2].textContent).toContain("completed");
    expect(badges[3].textContent).toContain("failed");
  });

  it("shows source type pill", () => {
    renderTable([makeItem({ source_type: "issue" })]);
    expect(screen.getByText("issue")).toBeDefined();
  });

  it("truncates long source values", () => {
    const longValue = "A".repeat(120);
    renderTable([makeItem({ source_value: longValue })]);
    // Should be truncated — the full string shouldn't appear
    const cell = screen.getByTestId("source-value-item-1");
    expect(cell.textContent!.length).toBeLessThan(120);
  });

  it("shows priority and demand count", () => {
    renderTable([makeItem({ priority: 80, demand_count: 3 })]);
    expect(screen.getByText("80")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
  });

  it("shows cost when non-zero", () => {
    renderTable([makeItem({ cost_usd: 1.23 })]);
    expect(screen.getByText("$1.23")).toBeDefined();
  });

  it("shows duration when non-zero", () => {
    renderTable([makeItem({ duration_ms: 65000 })]);
    expect(screen.getByText("1m 5s")).toBeDefined();
  });

  it("shows PR link when present", () => {
    renderTable([makeItem({ pr_url: "https://github.com/org/repo/pull/42" })]);
    const link = screen.getByRole("link", { name: /PR/i });
    expect(link.getAttribute("href")).toBe("https://github.com/org/repo/pull/42");
  });

  it("shows error tooltip when error is present", () => {
    renderTable([makeItem({ status: "failed", error: "Something went wrong" })]);
    expect(screen.getByText(/Something went wrong/)).toBeDefined();
  });

  it("renders empty state when no items", () => {
    renderTable([]);
    expect(screen.getByText(/no queue items/i)).toBeDefined();
  });
});
