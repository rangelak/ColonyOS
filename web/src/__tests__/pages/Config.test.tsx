import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Config from "../../pages/Config";

vi.mock("../../api", () => ({
  fetchConfig: vi.fn(),
  fetchHealth: vi.fn(),
  updateConfig: vi.fn(),
  updatePersonas: vi.fn(),
}));

import { fetchConfig, fetchHealth } from "../../api";
const mockFetchConfig = vi.mocked(fetchConfig);
const mockFetchHealth = vi.mocked(fetchHealth);

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchHealth.mockResolvedValue({ status: "ok", version: "1.0", write_enabled: "false" });
});

const mockConfig = {
  model: "sonnet",
  phase_models: { plan: "opus" },
  budget: {
    per_phase: 5.0,
    per_run: 15.0,
    max_duration_hours: 2,
    max_total_usd: 100.0,
  },
  phases: { plan: true, implement: true, review: true, deliver: false },
  branch_prefix: "colonyos/",
  prds_dir: "cOS_prds",
  tasks_dir: "cOS_tasks",
  reviews_dir: "cOS_reviews",
  proposals_dir: "cOS_proposals",
  max_fix_iterations: 3,
  auto_approve: false,
  learnings: { enabled: true, max_entries: 50 },
  ci_fix: { enabled: false, max_retries: 3, wait_timeout: 300, log_char_cap: 5000 },
  vision: "",
  project: { name: "test-project", description: "A test project", stack: "python" },
  personas: [
    {
      role: "Security Engineer",
      expertise: "AppSec",
      perspective: "defensive",
      reviewer: true,
    },
  ],
};

describe("Config", () => {
  it("shows loading state", () => {
    mockFetchConfig.mockReturnValue(new Promise(() => {}));
    render(<Config />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders config after fetch", async () => {
    mockFetchConfig.mockResolvedValueOnce(mockConfig);
    render(<Config />);

    await waitFor(() => {
      expect(screen.getByText("test-project")).toBeInTheDocument();
    });
    expect(screen.getByText("Security Engineer")).toBeInTheDocument();
  });

  it("shows error on fetch failure", async () => {
    mockFetchConfig.mockRejectedValueOnce(new Error("API error 500: Server Error"));
    render(<Config />);

    await waitFor(() => {
      expect(screen.getByText(/API error 500/)).toBeInTheDocument();
    });
  });

  it("renders budget values", async () => {
    mockFetchConfig.mockResolvedValueOnce(mockConfig);
    render(<Config />);

    await waitFor(() => {
      expect(screen.getByText("5.00")).toBeInTheDocument();
      expect(screen.getByText("15.00")).toBeInTheDocument();
      expect(screen.getByText("100.00")).toBeInTheDocument();
    });
  });

  it("renders phase toggles", async () => {
    mockFetchConfig.mockResolvedValueOnce(mockConfig);
    render(<Config />);

    await waitFor(() => {
      expect(screen.getByText("plan")).toBeInTheDocument();
      expect(screen.getByText("implement")).toBeInTheDocument();
      expect(screen.getByText("deliver")).toBeInTheDocument();
    });
  });
});
