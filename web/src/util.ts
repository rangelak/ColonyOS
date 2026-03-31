/** Shared utility functions. */

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainSec = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainSec}s`;
  const hours = Math.floor(minutes / 60);
  const remainMin = minutes % 60;
  return `${hours}h ${remainMin}m`;
}

/** Capitalize the first letter of a string. */
export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const STATUS_COLOR_MAP: Record<string, string> = {
  completed: "text-emerald-400",
  failed: "text-red-400",
  running: "text-amber-400",
};

export function statusColor(status: string): string {
  return STATUS_COLOR_MAP[status] ?? "text-gray-400";
}

const STATUS_ICON_MAP: Record<string, string> = {
  completed: "\u2713",
  failed: "\u2717",
  running: "\u25CB",
};

export function statusIcon(status: string): string {
  return STATUS_ICON_MAP[status] ?? "?";
}

export function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Queue-specific status colors (Tailwind classes). */
const QUEUE_STATUS_COLOR_MAP: Record<string, string> = {
  pending: "text-yellow-400",
  running: "text-blue-400",
  completed: "text-emerald-400",
  failed: "text-red-400",
  rejected: "text-gray-500",
};

export function queueStatusColor(status: string): string {
  return QUEUE_STATUS_COLOR_MAP[status] ?? "text-gray-400";
}

/** Queue-specific status background colors (Tailwind classes). */
const QUEUE_STATUS_BG_MAP: Record<string, string> = {
  pending: "bg-yellow-400/20 text-yellow-400",
  running: "bg-blue-400/20 text-blue-400",
  completed: "bg-emerald-400/20 text-emerald-400",
  failed: "bg-red-400/20 text-red-400",
  rejected: "bg-gray-500/20 text-gray-500",
};

export function queueStatusBg(status: string): string {
  return QUEUE_STATUS_BG_MAP[status] ?? "bg-gray-400/20 text-gray-400";
}

/** Queue status icon (unicode). */
const QUEUE_STATUS_ICON_MAP: Record<string, string> = {
  pending: "⏳",
  running: "▶",
  completed: "✓",
  failed: "✗",
  rejected: "⊘",
};

export function queueStatusIcon(status: string): string {
  return QUEUE_STATUS_ICON_MAP[status] ?? "?";
}

/** Daemon health status color (Tailwind classes). */
const HEALTH_STATUS_COLOR_MAP: Record<string, string> = {
  healthy: "text-emerald-400",
  degraded: "text-yellow-400",
  stopped: "text-red-400",
};

export function healthStatusColor(status: string): string {
  return HEALTH_STATUS_COLOR_MAP[status] ?? "text-gray-400";
}

/** Source type badge color (Tailwind classes). */
const SOURCE_TYPE_BG_MAP: Record<string, string> = {
  issue: "bg-blue-400/20 text-blue-400",
  slack: "bg-purple-400/20 text-purple-400",
  slack_fix: "bg-purple-400/20 text-purple-400",
  pr_review_fix: "bg-orange-400/20 text-orange-400",
  ceo: "bg-red-400/20 text-red-400",
  prompt: "bg-gray-400/20 text-gray-400",
};

export function sourceTypeBg(sourceType: string | null): string {
  return (sourceType && SOURCE_TYPE_BG_MAP[sourceType]) ?? "bg-gray-400/20 text-gray-400";
}

/** Human-readable source type label. */
const SOURCE_TYPE_LABEL_MAP: Record<string, string> = {
  issue: "Issue",
  slack: "Slack",
  slack_fix: "Slack Fix",
  pr_review_fix: "PR Review",
  ceo: "CEO",
  prompt: "Prompt",
  cleanup: "Cleanup",
  refactor: "Refactor",
};

export function sourceTypeLabel(sourceType: string | null): string {
  return (sourceType && SOURCE_TYPE_LABEL_MAP[sourceType]) ?? sourceType ?? "Unknown";
}

/** Daemon health status dot color (Tailwind bg classes). */
const HEALTH_STATUS_DOT_MAP: Record<string, string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-yellow-400",
  stopped: "bg-red-400",
};

export function healthStatusDot(status: string): string {
  return HEALTH_STATUS_DOT_MAP[status] ?? "bg-gray-400";
}
