import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AuthTokenPrompt from "../../components/AuthTokenPrompt";

// Mock the api module
vi.mock("../../api", () => ({
  getAuthToken: vi.fn(),
  setAuthToken: vi.fn(),
  fetchHealth: vi.fn(),
}));

import { getAuthToken, setAuthToken, fetchHealth } from "../../api";
const mockGetAuthToken = vi.mocked(getAuthToken);
const mockSetAuthToken = vi.mocked(setAuthToken);
const mockFetchHealth = vi.mocked(fetchHealth);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AuthTokenPrompt", () => {
  it("does not render when token already exists", async () => {
    mockGetAuthToken.mockReturnValue("existing-token");

    const { container } = render(<AuthTokenPrompt />);

    // Should not show the dialog
    await waitFor(() => {
      expect(container.querySelector(".fixed")).toBeNull();
    });
  });

  it("does not render when write mode is disabled", async () => {
    mockGetAuthToken.mockReturnValue(null);
    mockFetchHealth.mockResolvedValueOnce({
      status: "ok",
      version: "1.0.0",
      write_enabled: "false",
    });

    const { container } = render(<AuthTokenPrompt />);

    await waitFor(() => {
      expect(container.querySelector(".fixed")).toBeNull();
    });
  });

  it("shows prompt when write mode is enabled and no token exists", async () => {
    mockGetAuthToken.mockReturnValue(null);
    mockFetchHealth.mockResolvedValueOnce({
      status: "ok",
      version: "1.0.0",
      write_enabled: "true",
    });

    render(<AuthTokenPrompt />);

    await waitFor(() => {
      expect(screen.getByText("Authentication Required")).toBeDefined();
    });
  });

  it("saves token and closes on submit", async () => {
    mockGetAuthToken.mockReturnValue(null);
    mockFetchHealth.mockResolvedValueOnce({
      status: "ok",
      version: "1.0.0",
      write_enabled: "true",
    });

    render(<AuthTokenPrompt />);

    await waitFor(() => {
      expect(screen.getByText("Save Token")).toBeDefined();
    });

    const input = screen.getByPlaceholderText("Paste bearer token here...");
    fireEvent.change(input, { target: { value: "my-secret-token" } });
    fireEvent.click(screen.getByText("Save Token"));

    expect(mockSetAuthToken).toHaveBeenCalledWith("my-secret-token");
  });

  it("dismisses without saving when Skip is clicked", async () => {
    mockGetAuthToken.mockReturnValue(null);
    mockFetchHealth.mockResolvedValueOnce({
      status: "ok",
      version: "1.0.0",
      write_enabled: "true",
    });

    render(<AuthTokenPrompt />);

    await waitFor(() => {
      expect(screen.getByText("Skip (read-only)")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Skip (read-only)"));

    await waitFor(() => {
      expect(screen.queryByText("Authentication Required")).toBeNull();
    });

    expect(mockSetAuthToken).not.toHaveBeenCalled();
  });
});
