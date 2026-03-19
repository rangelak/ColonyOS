import type { PhaseTimelineEntry } from "../types";
import { formatDuration } from "../util";

function phaseIcon(entry: PhaseTimelineEntry): string {
  if (entry.is_skipped) return "\u23ED";
  return entry.success ? "\u2713" : "\u2717";
}

function phaseColor(entry: PhaseTimelineEntry): string {
  if (entry.is_skipped) return "text-gray-500";
  return entry.success ? "text-emerald-400" : "text-red-400";
}

export default function PhaseTimeline({
  entries,
}: {
  entries: PhaseTimelineEntry[];
}) {
  if (entries.length === 0) {
    return <p className="text-gray-500 text-sm">No phases recorded.</p>;
  }

  return (
    <div className="space-y-1">
      {entries.map((entry, idx) => (
        <div
          key={idx}
          className="flex items-start gap-3 py-2 px-3 rounded hover:bg-gray-800/40 transition-colors"
        >
          {/* Status icon */}
          <span className={`text-lg mt-0.5 ${phaseColor(entry)}`}>
            {phaseIcon(entry)}
          </span>

          {/* Phase details */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-200 text-sm">
                {entry.phase}
              </span>
              {entry.model && (
                <span className="text-xs bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                  {entry.model}
                </span>
              )}
              {entry.is_collapsed && (
                <span className="text-xs text-gray-500">
                  ({entry.collapsed_count} reviews)
                </span>
              )}
            </div>
            {entry.error && (
              <p className="text-xs text-red-400 mt-1 truncate">{entry.error}</p>
            )}
          </div>

          {/* Cost & duration */}
          <div className="text-right text-xs text-gray-500 shrink-0">
            {entry.cost_usd != null && (
              <div className="font-mono">${entry.cost_usd.toFixed(2)}</div>
            )}
            {entry.duration_ms > 0 && (
              <div>{formatDuration(entry.duration_ms)}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
