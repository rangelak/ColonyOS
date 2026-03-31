import type { QueueItem } from "../types";
import { queueStatusBg, formatDuration, formatTimestamp } from "../util";

interface QueueTableProps {
  items: QueueItem[];
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

export default function QueueTable({ items }: QueueTableProps) {
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No queue items to display.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 text-xs border-b border-gray-800">
            <th className="pb-2 pr-3 font-medium">Status</th>
            <th className="pb-2 pr-3 font-medium">Source</th>
            <th className="pb-2 pr-3 font-medium">Value</th>
            <th className="pb-2 pr-3 font-medium text-right">Priority</th>
            <th className="pb-2 pr-3 font-medium text-right">Demand</th>
            <th className="pb-2 pr-3 font-medium text-right">Cost</th>
            <th className="pb-2 pr-3 font-medium text-right">Duration</th>
            <th className="pb-2 pr-3 font-medium">Added</th>
            <th className="pb-2 font-medium">Link</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              {/* Status badge */}
              <td className="py-2 pr-3">
                <span
                  data-testid="queue-status-badge"
                  className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${queueStatusBg(item.status)}`}
                >
                  {item.status}
                </span>
              </td>

              {/* Source type pill */}
              <td className="py-2 pr-3">
                <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 font-mono">
                  {item.source_type}
                </span>
              </td>

              {/* Source value (truncated) */}
              <td
                className="py-2 pr-3 max-w-[280px]"
                data-testid={`source-value-${item.id}`}
              >
                <span className="text-gray-200 truncate block" title={item.source_value}>
                  {truncate(item.source_value, 80)}
                </span>
              </td>

              {/* Priority */}
              <td className="py-2 pr-3 text-right text-gray-400">
                {item.priority}
              </td>

              {/* Demand count */}
              <td className="py-2 pr-3 text-right text-gray-400">
                {item.demand_count}
              </td>

              {/* Cost */}
              <td className="py-2 pr-3 text-right text-gray-300 font-mono">
                {item.cost_usd > 0 ? `$${item.cost_usd.toFixed(2)}` : "—"}
              </td>

              {/* Duration */}
              <td className="py-2 pr-3 text-right text-gray-400">
                {item.duration_ms > 0 ? formatDuration(item.duration_ms) : "—"}
              </td>

              {/* Added timestamp */}
              <td className="py-2 pr-3 text-gray-500 text-xs whitespace-nowrap">
                {formatTimestamp(item.added_at)}
              </td>

              {/* PR link */}
              <td className="py-2">
                {item.pr_url ? (
                  <a
                    href={item.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-emerald-400 hover:text-emerald-300 text-xs font-medium"
                  >
                    PR ↗
                  </a>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Error details for failed items */}
      {items
        .filter((item) => item.error)
        .map((item) => (
          <div
            key={`error-${item.id}`}
            className="mt-1 px-3 py-2 bg-red-900/20 border border-red-800/30 rounded text-xs text-red-300"
          >
            <span className="font-medium text-red-400">Error ({truncate(item.source_value, 40)}):</span>{" "}
            {item.error}
          </div>
        ))}
    </div>
  );
}
