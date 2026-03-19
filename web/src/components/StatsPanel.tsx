import type { RunSummary } from "../types";

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
}

function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="text-2xl font-bold text-gray-100 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}

export default function StatsPanel({ summary }: { summary: RunSummary }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard label="Total Runs" value={String(summary.total_runs)} />
      <StatCard
        label="Success Rate"
        value={`${summary.success_rate.toFixed(1)}%`}
        sub={`${summary.completed} completed, ${summary.failed} failed`}
      />
      <StatCard
        label="Total Cost"
        value={`$${summary.total_cost_usd.toFixed(2)}`}
        sub={
          summary.total_runs > 0
            ? `$${(summary.total_cost_usd / summary.total_runs).toFixed(2)} avg/run`
            : undefined
        }
      />
      <StatCard
        label="In Progress"
        value={String(summary.in_progress)}
      />
    </div>
  );
}
