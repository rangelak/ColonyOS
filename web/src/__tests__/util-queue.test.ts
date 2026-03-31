import { describe, it, expect } from "vitest";
import {
  capitalize,
  queueStatusColor,
  queueStatusBg,
  queueStatusIcon,
  healthStatusColor,
  healthStatusDot,
  sourceTypeBg,
  sourceTypeLabel,
} from "../util";

describe("capitalize", () => {
  it("capitalizes a lowercase string", () => {
    expect(capitalize("healthy")).toBe("Healthy");
  });

  it("returns already-capitalized string unchanged", () => {
    expect(capitalize("Running")).toBe("Running");
  });

  it("handles empty string", () => {
    expect(capitalize("")).toBe("");
  });

  it("handles single character", () => {
    expect(capitalize("a")).toBe("A");
  });
});

describe("sourceTypeBg", () => {
  it("returns blue for issue", () => {
    expect(sourceTypeBg("issue")).toContain("blue");
  });

  it("returns purple for slack", () => {
    expect(sourceTypeBg("slack")).toContain("purple");
  });

  it("returns default gray for null", () => {
    expect(sourceTypeBg(null)).toContain("gray");
  });

  it("returns default gray for unknown type", () => {
    expect(sourceTypeBg("unknown")).toContain("gray");
  });
});

describe("sourceTypeLabel", () => {
  it("returns Issue for issue", () => {
    expect(sourceTypeLabel("issue")).toBe("Issue");
  });

  it("returns Slack Fix for slack_fix", () => {
    expect(sourceTypeLabel("slack_fix")).toBe("Slack Fix");
  });

  it("returns raw value for unknown type", () => {
    expect(sourceTypeLabel("custom")).toBe("custom");
  });

  it("returns Unknown for null", () => {
    expect(sourceTypeLabel(null)).toBe("Unknown");
  });
});

describe("queueStatusColor", () => {
  it("returns yellow for pending", () => {
    expect(queueStatusColor("pending")).toBe("text-yellow-400");
  });

  it("returns blue for running", () => {
    expect(queueStatusColor("running")).toBe("text-blue-400");
  });

  it("returns green for completed", () => {
    expect(queueStatusColor("completed")).toBe("text-emerald-400");
  });

  it("returns red for failed", () => {
    expect(queueStatusColor("failed")).toBe("text-red-400");
  });

  it("returns gray for rejected", () => {
    expect(queueStatusColor("rejected")).toBe("text-gray-500");
  });

  it("returns gray for unknown status", () => {
    expect(queueStatusColor("unknown")).toBe("text-gray-400");
  });
});

describe("queueStatusBg", () => {
  it("returns yellow bg for pending", () => {
    expect(queueStatusBg("pending")).toContain("yellow");
  });

  it("returns blue bg for running", () => {
    expect(queueStatusBg("running")).toContain("blue");
  });

  it("returns green bg for completed", () => {
    expect(queueStatusBg("completed")).toContain("emerald");
  });

  it("returns red bg for failed", () => {
    expect(queueStatusBg("failed")).toContain("red");
  });
});

describe("queueStatusIcon", () => {
  it("returns hourglass for pending", () => {
    expect(queueStatusIcon("pending")).toBe("⏳");
  });

  it("returns play for running", () => {
    expect(queueStatusIcon("running")).toBe("▶");
  });

  it("returns check for completed", () => {
    expect(queueStatusIcon("completed")).toBe("✓");
  });

  it("returns x for failed", () => {
    expect(queueStatusIcon("failed")).toBe("✗");
  });

  it("returns ? for unknown", () => {
    expect(queueStatusIcon("unknown")).toBe("?");
  });
});

describe("healthStatusColor", () => {
  it("returns green for healthy", () => {
    expect(healthStatusColor("healthy")).toBe("text-emerald-400");
  });

  it("returns yellow for degraded", () => {
    expect(healthStatusColor("degraded")).toBe("text-yellow-400");
  });

  it("returns red for stopped", () => {
    expect(healthStatusColor("stopped")).toBe("text-red-400");
  });

  it("returns gray for unknown", () => {
    expect(healthStatusColor("unknown")).toBe("text-gray-400");
  });
});

describe("healthStatusDot", () => {
  it("returns green bg for healthy", () => {
    expect(healthStatusDot("healthy")).toBe("bg-emerald-400");
  });

  it("returns yellow bg for degraded", () => {
    expect(healthStatusDot("degraded")).toBe("bg-yellow-400");
  });

  it("returns red bg for stopped", () => {
    expect(healthStatusDot("stopped")).toBe("bg-red-400");
  });
});
