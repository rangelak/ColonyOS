import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import DaemonHealthBanner from "../../components/DaemonHealthBanner";
import type { DaemonHealth } from "../../types";

function makeHealth(overrides: Partial<DaemonHealth> = {}): DaemonHealth {
  return {
    status: "healthy",
    heartbeat_age_seconds: 2,
    queue_depth: 3,
    daily_spend_usd: 12.5,
    daily_budget_remaining_usd: 37.5,
    circuit_breaker_active: false,
    paused: false,
    total_items_today: 8,
    consecutive_failures: 0,
    ...overrides,
  };
}

// Mock the api module
vi.mock("../../api", () => ({
  fetchDaemonHealth: vi.fn(),
  fetchHealth: vi.fn(),
  pauseDaemon: vi.fn(),
  resumeDaemon: vi.fn(),
}));

import {
  fetchDaemonHealth,
  fetchHealth,
  pauseDaemon,
  resumeDaemon,
} from "../../api";

const mockFetchDaemonHealth = fetchDaemonHealth as ReturnType<typeof vi.fn>;
const mockFetchHealth = fetchHealth as ReturnType<typeof vi.fn>;
const mockPauseDaemon = pauseDaemon as ReturnType<typeof vi.fn>;
const mockResumeDaemon = resumeDaemon as ReturnType<typeof vi.fn>;

function renderBanner() {
  return render(
    <MemoryRouter>
      <DaemonHealthBanner />
    </MemoryRouter>
  );
}

describe("DaemonHealthBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockFetchHealth.mockResolvedValue({
      status: "ok",
      version: "1.0.0",
      write_enabled: "true",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders healthy state with green dot and status text", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth());
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText("Healthy")).toBeDefined();
    });
    // Green dot should be present
    const dot = screen.getByTestId("health-dot");
    expect(dot.className).toContain("bg-emerald-400");
  });

  it("renders degraded state with yellow dot", async () => {
    mockFetchDaemonHealth.mockResolvedValue(
      makeHealth({ status: "degraded", consecutive_failures: 3 })
    );
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText("Degraded")).toBeDefined();
    });
    const dot = screen.getByTestId("health-dot");
    expect(dot.className).toContain("bg-yellow-400");
  });

  it("renders stopped state with red dot", async () => {
    mockFetchDaemonHealth.mockResolvedValue(
      makeHealth({ status: "stopped" })
    );
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText("Stopped")).toBeDefined();
    });
    const dot = screen.getByTestId("health-dot");
    expect(dot.className).toContain("bg-red-400");
  });

  it("shows daily spend and budget info", async () => {
    mockFetchDaemonHealth.mockResolvedValue(
      makeHealth({ daily_spend_usd: 12.5, daily_budget_remaining_usd: 37.5 })
    );
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText(/\$12\.50/)).toBeDefined();
    });
  });

  it("shows circuit breaker warning when active", async () => {
    mockFetchDaemonHealth.mockResolvedValue(
      makeHealth({ circuit_breaker_active: true })
    );
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText(/circuit breaker/i)).toBeDefined();
    });
  });

  it("shows paused warning when daemon is paused", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: true }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText(/paused/i)).toBeDefined();
    });
  });

  it("shows queue depth", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ queue_depth: 5 }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText(/Q:\s*5/)).toBeDefined();
    });
  });

  it("handles fetch error gracefully", async () => {
    mockFetchDaemonHealth.mockRejectedValue(new Error("Network error"));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText(/unreachable/i)).toBeDefined();
    });
  });

  it("polls health every 5 seconds", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth());
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText("Healthy")).toBeDefined();
    });
    const callsBefore = mockFetchDaemonHealth.mock.calls.length;
    // Advance by 5 seconds
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await waitFor(() => {
      expect(mockFetchDaemonHealth.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it("shows pause button when write is enabled and daemon is running", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: false }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /pause/i })).toBeDefined();
    });
  });

  it("shows resume button when daemon is paused", async () => {
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: true }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /resume/i })).toBeDefined();
    });
  });

  it("hides pause/resume button when write is not enabled", async () => {
    mockFetchHealth.mockResolvedValue({
      status: "ok",
      version: "1.0.0",
      write_enabled: "false",
    });
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: false }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByText("Healthy")).toBeDefined();
    });
    expect(screen.queryByRole("button", { name: /pause/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume/i })).toBeNull();
  });

  it("shows confirmation dialog when pause is clicked", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: false }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /pause/i })).toBeDefined();
    });
    await user.click(screen.getByRole("button", { name: /pause/i }));
    expect(screen.getByText(/are you sure/i)).toBeDefined();
  });

  it("calls pauseDaemon when confirmation is accepted", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: false }));
    mockPauseDaemon.mockResolvedValue(makeHealth({ paused: true }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /pause/i })).toBeDefined();
    });
    await user.click(screen.getByRole("button", { name: /pause/i }));
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(mockPauseDaemon).toHaveBeenCalled();
  });

  it("calls resumeDaemon when resume is clicked and confirmed", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetchDaemonHealth.mockResolvedValue(makeHealth({ paused: true }));
    mockResumeDaemon.mockResolvedValue(makeHealth({ paused: false }));
    await act(async () => {
      renderBanner();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /resume/i })).toBeDefined();
    });
    await user.click(screen.getByRole("button", { name: /resume/i }));
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(mockResumeDaemon).toHaveBeenCalled();
  });
});
