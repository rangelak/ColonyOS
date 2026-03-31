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

export function statusColor(status: string): string {
  switch (status) {
    case "completed":
      return "text-emerald-400";
    case "failed":
      return "text-red-400";
    case "running":
      return "text-amber-400";
    default:
      return "text-gray-400";
  }
}

export function statusIcon(status: string): string {
  switch (status) {
    case "completed":
      return "\u2713";
    case "failed":
      return "\u2717";
    case "running":
      return "\u25CB";
    default:
      return "?";
  }
}

export function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Queue-specific status colors (Tailwind classes). */
export function queueStatusColor(status: string): string {
  switch (status) {
    case "pending":
      return "text-yellow-400";
    case "running":
      return "text-blue-400";
    case "completed":
      return "text-emerald-400";
    case "failed":
      return "text-red-400";
    case "rejected":
      return "text-gray-500";
    default:
      return "text-gray-400";
  }
}

/** Queue-specific status background colors (Tailwind classes). */
export function queueStatusBg(status: string): string {
  switch (status) {
    case "pending":
      return "bg-yellow-400/20 text-yellow-400";
    case "running":
      return "bg-blue-400/20 text-blue-400";
    case "completed":
      return "bg-emerald-400/20 text-emerald-400";
    case "failed":
      return "bg-red-400/20 text-red-400";
    case "rejected":
      return "bg-gray-500/20 text-gray-500";
    default:
      return "bg-gray-400/20 text-gray-400";
  }
}

/** Queue status icon (unicode). */
export function queueStatusIcon(status: string): string {
  switch (status) {
    case "pending":
      return "⏳";
    case "running":
      return "▶";
    case "completed":
      return "✓";
    case "failed":
      return "✗";
    case "rejected":
      return "⊘";
    default:
      return "?";
  }
}

/** Daemon health status color (Tailwind classes). */
export function healthStatusColor(status: string): string {
  switch (status) {
    case "healthy":
      return "text-emerald-400";
    case "degraded":
      return "text-yellow-400";
    case "stopped":
      return "text-red-400";
    default:
      return "text-gray-400";
  }
}

/** Daemon health status dot color (Tailwind bg classes). */
export function healthStatusDot(status: string): string {
  switch (status) {
    case "healthy":
      return "bg-emerald-400";
    case "degraded":
      return "bg-yellow-400";
    case "stopped":
      return "bg-red-400";
    default:
      return "bg-gray-400";
  }
}
