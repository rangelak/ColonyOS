import { Link } from "react-router-dom";
import type { RunLog } from "../types";
import { formatDuration, statusColor, statusIcon, sourceTypeBg, sourceTypeLabel } from "../util";

export default function RunList({ runs }: { runs: RunLog[] }) {
  if (runs.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg">No runs yet</p>
        <p className="text-sm mt-1">
          Run <code className="text-emerald-400">colonyos run "your prompt"</code> to get started.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-gray-500 uppercase text-xs tracking-wider">
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Source</th>
            <th className="px-4 py-3">Run ID</th>
            <th className="px-4 py-3">Prompt</th>
            <th className="px-4 py-3 text-right">Cost</th>
            <th className="px-4 py-3 text-right">Duration</th>
            <th className="px-4 py-3 text-right">Phases</th>
            <th className="px-4 py-3">PR</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {runs.map((run) => {
            const wallMs = run.finished_at && run.started_at
              ? new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
              : 0;
            return (
              <tr key={run.run_id} className="hover:bg-gray-800/50 transition-colors">
                <td className="px-4 py-3">
                  <span className={`font-medium ${statusColor(run.status)}`}>
                    {statusIcon(run.status)} {run.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-block text-xs px-1.5 py-0.5 rounded font-medium ${sourceTypeBg(run.source_type)}`}>
                    {sourceTypeLabel(run.source_type)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <Link
                    to={`/runs/${encodeURIComponent(run.run_id)}`}
                    className="text-emerald-400 hover:underline font-mono text-xs"
                  >
                    {run.run_id}
                  </Link>
                </td>
                <td className="px-4 py-3 text-gray-300 max-w-xs truncate">
                  {run.prompt}
                </td>
                <td className="px-4 py-3 text-right text-gray-300 font-mono">
                  ${(run.total_cost_usd ?? 0).toFixed(2)}
                </td>
                <td className="px-4 py-3 text-right text-gray-400">
                  {wallMs > 0 ? formatDuration(wallMs) : "-"}
                </td>
                <td className="px-4 py-3 text-right text-gray-400">
                  {run.phases.length}
                </td>
                <td className="px-4 py-3">
                  {run.pr_url ? (
                    <a
                      href={run.pr_url}
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
