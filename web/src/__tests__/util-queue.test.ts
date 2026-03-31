import { describe, it, expect } from "vitest";
import {
  queueStatusColor,
  queueStatusBg,
  queueStatusIcon,
  healthStatusColor,
  healthStatusDot,
} from "../util";

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
