import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PersonaCard from "../../components/PersonaCard";
import type { Persona } from "../../types";

const basePersona: Persona = {
  role: "Security Engineer",
  expertise: "Application Security",
  perspective: "defensive coding practices",
  reviewer: false,
};

describe("PersonaCard", () => {
  it("renders persona role, expertise, and perspective", () => {
    render(<PersonaCard persona={basePersona} />);

    expect(screen.getByText("Security Engineer")).toBeInTheDocument();
    expect(screen.getByText("Application Security")).toBeInTheDocument();
    expect(screen.getByText("defensive coding practices")).toBeInTheDocument();
  });

  it("shows reviewer badge when persona is a reviewer", () => {
    const reviewer = { ...basePersona, reviewer: true };
    render(<PersonaCard persona={reviewer} />);

    expect(screen.getByText("Reviewer")).toBeInTheDocument();
  });

  it("hides reviewer badge when persona is not a reviewer", () => {
    render(<PersonaCard persona={basePersona} />);

    expect(screen.queryByText("Reviewer")).not.toBeInTheDocument();
  });
});
