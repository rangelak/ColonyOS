import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ArtifactPreview from "../../components/ArtifactPreview";

// Mock the api module
vi.mock("../../api", () => ({
  fetchArtifact: vi.fn(),
}));

import { fetchArtifact } from "../../api";
const mockFetchArtifact = vi.mocked(fetchArtifact);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ArtifactPreview", () => {
  it("renders collapsed by default with the path as label", () => {
    render(<ArtifactPreview path="cOS_prds/test.md" />);
    expect(screen.getByText("cOS_prds/test.md")).toBeDefined();
    expect(screen.queryByText("Loading...")).toBeNull();
  });

  it("renders custom title when provided", () => {
    render(<ArtifactPreview path="cOS_prds/test.md" title="PRD Preview" />);
    expect(screen.getByText("PRD Preview")).toBeDefined();
  });

  it("fetches and renders markdown content when expanded", async () => {
    mockFetchArtifact.mockResolvedValueOnce({
      content: "# Hello World\n\nThis is **bold** text.",
      path: "cOS_prds/test.md",
      filename: "test.md",
    });

    render(<ArtifactPreview path="cOS_prds/test.md" />);

    // Click to expand
    fireEvent.click(screen.getByText("cOS_prds/test.md"));

    // Should show loading
    expect(screen.getByText("Loading...")).toBeDefined();

    // Wait for content to render as HTML (not raw markdown)
    await waitFor(() => {
      const contentDiv = document.querySelector(".prose");
      expect(contentDiv).not.toBeNull();
      expect(contentDiv!.innerHTML).toContain("<h1");
      expect(contentDiv!.innerHTML).toContain("<strong>");
    });
  });

  it("neutralizes HTML tags in content to prevent XSS", async () => {
    // Content containing raw HTML tags that should be HTML-entity-escaped
    mockFetchArtifact.mockResolvedValueOnce({
      content: '<script>alert("xss")</script>\n\n# Safe Heading\n\n<img onerror="alert(1)" src=x>',
      path: "cOS_prds/xss.md",
      filename: "xss.md",
    });

    render(<ArtifactPreview path="cOS_prds/xss.md" />);
    fireEvent.click(screen.getByText("cOS_prds/xss.md"));

    await waitFor(() => {
      const contentDiv = document.querySelector(".prose");
      expect(contentDiv).not.toBeNull();
      const html = contentDiv!.innerHTML;
      // Raw script/img tags must be HTML-entity-escaped, not rendered as DOM elements
      expect(html).not.toContain("<script>");
      expect(html).not.toContain("<img");
      // The escaped versions should be present (proving content is preserved but safe)
      expect(html).toContain("&lt;script&gt;");
      expect(html).toContain("&lt;img");
      // Safe markdown rendering should still work
      expect(html).toContain("<h1");
    });
  });

  it("shows error message on fetch failure", async () => {
    mockFetchArtifact.mockRejectedValueOnce(new Error("Not found"));

    render(<ArtifactPreview path="cOS_prds/missing.md" />);

    fireEvent.click(screen.getByText("cOS_prds/missing.md"));

    await waitFor(() => {
      expect(screen.getByText(/Not found/)).toBeDefined();
    });
  });
});
