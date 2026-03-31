import type { RunSummary, ReviewLoopStats } from "../types";

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

interface StatsPanelProps {
  summary: RunSummary;
  reviewLoop?: ReviewLoopStats;
}

export default function StatsPanel({ summary, reviewLoop }: StatsPanelProps) {
  const avgCost = summary.total_runs > 0
    ? (summary.total_cost_usd / summary.total_runs).toFixed(2)
    : "0.00";

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard label="Total Runs" value={String(summary.total_runs)} />
      <StatCard
        label="Success Rate"
        value={`${summary.success_rate.toFixed(1)}%`}
        sub={`${summary.completed} completed, ${summary.failed} failed`}
      />
      <StatCard
        label="Failure Rate"
        value={`${summary.failure_rate.toFixed(1)}%`}
        sub={`${summary.failed} of ${summary.total_runs} runs`}
      />
      <StatCard
        label="Total Cost"
        value={`$${summary.total_cost_usd.toFixed(2)}`}
        sub={`$${avgCost} avg/run`}
      />
      <StatCard
        label="Avg Cost / Run"
        value={`$${avgCost}`}
      />
      <StatCard
        label="In Progress"
        value={String(summary.in_progress)}
      />
      {reviewLoop && (
        <>
          <StatCard
            label="First-Pass Approval"
            value={`${(reviewLoop.first_pass_approval_rate * 100).toFixed(0)}%`}
            sub={`${reviewLoop.total_review_rounds} review rounds total`}
          />
          <StatCard
            label="Avg Review Rounds"
            value={reviewLoop.avg_review_rounds.toFixed(1)}
            sub={`${reviewLoop.total_fix_iterations} fix iterations`}
          />
        </>
      )}
    </div>
  );
}
