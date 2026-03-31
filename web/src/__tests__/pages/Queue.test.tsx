import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Queue from "../../pages/Queue";
import type { QueueState, QueueItem } from "../../types";

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

function makeQueueState(items: QueueItem[]): QueueState {
  const totalCost = items.reduce((sum, i) => sum + i.cost_usd, 0);
  return {
    queue_id: "q-1",
    items,
    aggregate_cost_usd: totalCost,
    start_time_iso: "2026-03-30T10:00:00Z",
    status: "active",
  };
}

vi.mock("../../api", () => ({
  fetchQueue: vi.fn(),
}));

import { fetchQueue } from "../../api";
const mockFetchQueue = fetchQueue as ReturnType<typeof vi.fn>;

function renderQueue() {
  return render(
    <MemoryRouter>
      <Queue />
    </MemoryRouter>
  );
}

describe("Queue page", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders queue items from API", async () => {
    mockFetchQueue.mockResolvedValue(
      makeQueueState([
        makeItem({ id: "item-1", source_value: "Fix login" }),
        makeItem({ id: "item-2", source_value: "Update docs", status: "completed", cost_usd: 2.5 }),
      ])
    );
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/Fix login/)).toBeDefined();
      expect(screen.getByText(/Update docs/)).toBeDefined();
    });
  });

  it("shows aggregate cost", async () => {
    mockFetchQueue.mockResolvedValue(
      makeQueueState([
        makeItem({ cost_usd: 1.5 }),
        makeItem({ id: "item-2", cost_usd: 2.5 }),
      ])
    );
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/\$4\.00/)).toBeDefined();
    });
  });

  it("filters by status when clicking tabs", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetchQueue.mockResolvedValue(
      makeQueueState([
        makeItem({ id: "item-1", source_value: "Pending task", status: "pending" }),
        makeItem({ id: "item-2", source_value: "Completed task", status: "completed" }),
        makeItem({ id: "item-3", source_value: "Failed task", status: "failed" }),
      ])
    );
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/Pending task/)).toBeDefined();
    });

    // Click "Completed" tab
    await user.click(screen.getByRole("button", { name: /completed/i }));
    expect(screen.getByText(/Completed task/)).toBeDefined();
    expect(screen.queryByText(/Pending task/)).toBeNull();

    // Click "All" tab
    await user.click(screen.getByRole("button", { name: /^all/i }));
    expect(screen.getByText(/Pending task/)).toBeDefined();
    expect(screen.getByText(/Completed task/)).toBeDefined();
  });

  it("shows empty state when queue is null", async () => {
    mockFetchQueue.mockResolvedValue(null);
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/no queue/i)).toBeDefined();
    });
  });

  it("polls queue every 5 seconds", async () => {
    mockFetchQueue.mockResolvedValue(makeQueueState([makeItem()]));
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/Fix the login bug/)).toBeDefined();
    });
    const callsBefore = mockFetchQueue.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await waitFor(() => {
      expect(mockFetchQueue.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it("handles fetch error gracefully", async () => {
    mockFetchQueue.mockRejectedValue(new Error("Network error"));
    await act(async () => {
      renderQueue();
    });
    await waitFor(() => {
      expect(screen.getByText(/failed to load/i)).toBeDefined();
    });
  });
});
