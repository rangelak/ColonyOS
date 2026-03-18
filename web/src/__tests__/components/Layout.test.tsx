import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Layout from "../../components/Layout";

function renderLayout(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Layout>
        <div data-testid="child-content">Page content</div>
      </Layout>
    </MemoryRouter>
  );
}

describe("Layout", () => {
  it("renders the ColonyOS brand title", () => {
    renderLayout();
    expect(screen.getByText("ColonyOS")).toBeDefined();
  });

  it("renders Dashboard subtitle and nav link", () => {
    renderLayout();
    // "Dashboard" appears as both the subtitle text and a nav link
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThanOrEqual(2);
  });

  it("renders navigation links", () => {
    renderLayout();
    expect(screen.getByText("Config")).toBeDefined();
    expect(screen.getByText("Proposals")).toBeDefined();
    expect(screen.getByText("Reviews")).toBeDefined();
  });

  it("renders children content", () => {
    renderLayout();
    expect(screen.getByTestId("child-content")).toBeDefined();
    expect(screen.getByText("Page content")).toBeDefined();
  });

  it("highlights the active navigation link", () => {
    renderLayout("/config");
    const configLink = screen.getByText("Config");
    expect(configLink.className).toContain("emerald");
  });
});
