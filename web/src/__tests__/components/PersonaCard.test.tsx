import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("shows remove button when editable", () => {
    const onRemove = vi.fn();
    render(<PersonaCard persona={basePersona} editable onRemove={onRemove} />);

    expect(screen.getByText("Remove")).toBeInTheDocument();
  });

  it("does not show remove button when not editable", () => {
    render(<PersonaCard persona={basePersona} />);

    expect(screen.queryByText("Remove")).not.toBeInTheDocument();
  });

  it("enters edit mode when clicked and editable", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<PersonaCard persona={basePersona} editable onSave={onSave} />);

    await user.click(screen.getByText("Security Engineer"));
    expect(screen.getByDisplayValue("Security Engineer")).toBeInTheDocument();
    expect(screen.getByText("Save")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });
});
