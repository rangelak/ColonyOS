import { useState, useEffect, useRef, useCallback } from "react";
import { fetchStats } from "../api";
import type { StatsResult } from "../types";
import CostChart from "../components/CostChart";
import { PhaseCostChart, FailureHotspotsChart } from "../components/PhaseBreakdownChart";
import { formatDuration } from "../util";

export default function Analytics() {
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const statsRef = useRef(stats);
  statsRef.current = stats;

  const load = useCallback(async () => {
    try {
      const data = await fetchStats();
      setStats(data);
      setError(null);
    } catch (err) {
      if (!statsRef.current) {
        setError(err instanceof Error ? err.message : "Failed to load stats");
      }
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  if (error && !stats) {
    return (
      <div className="text-red-400 p-4" data-testid="analytics-error">
        Failed to load analytics: {error}
      </div>
    );
  }

  if (!stats) {
    return <div className="text-gray-400 p-4">Loading analytics...</div>;
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-100">Analytics</h2>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="analytics-summary">
        <SummaryCard
          label="Total Runs"
          value={String(stats.summary.total_runs)}
        />
        <SummaryCard
          label="Success Rate"
          value={`${(stats.summary.success_rate * 100).toFixed(0)}%`}
          color={stats.summary.success_rate >= 0.7 ? "text-emerald-400" : "text-yellow-400"}
        />
        <SummaryCard
          label="Total Cost"
          value={`$${stats.summary.total_cost_usd.toFixed(2)}`}
        />
        <SummaryCard
          label="In Progress"
          value={String(stats.summary.in_progress)}
        />
      </div>

      {/* Cost trend */}
      <ChartCard title="Cost Trend" subtitle="Cost per recent run">
        <CostChart data={stats.recent_trend} />
      </ChartCard>

      {/* Phase breakdown + failure hotspots side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Phase Cost Breakdown" subtitle="Total and average cost per phase">
          <PhaseCostChart data={stats.cost_breakdown} />
        </ChartCard>

        <ChartCard title="Failure Hotspots" subtitle="Failure rate by phase">
          <FailureHotspotsChart data={stats.failure_hotspots} />
        </ChartCard>
      </div>

      {/* Model usage + Duration stats side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Model Usage" subtitle="Invocations and cost by model">
          <ModelUsageTable data={stats.model_usage} />
        </ChartCard>

        <ChartCard title="Duration Stats" subtitle="Average duration by phase">
          <DurationTable data={stats.duration_stats} />
        </ChartCard>
      </div>

      {/* Review loop summary */}
      <ChartCard title="Review Loop" subtitle="Review and fix iteration stats">
        <ReviewLoopSummary data={stats.review_loop} />
      </ChartCard>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color ?? "text-gray-100"}`}>{value}</div>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
      <p className="text-xs text-gray-500 mb-4">{subtitle}</p>
      {children}
    </div>
  );
}

function ModelUsageTable({ data }: { data: StatsResult["model_usage"] }) {
  if (data.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-8" data-testid="model-usage-empty">
        No model usage data yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto" data-testid="model-usage-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs uppercase border-b border-gray-800">
            <th className="text-left py-2 pr-4">Model</th>
            <th className="text-right py-2 px-2">Invocations</th>
            <th className="text-right py-2 px-2">Total Cost</th>
            <th className="text-right py-2 pl-2">Avg Cost</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.model} className="border-b border-gray-800/50">
              <td className="py-2 pr-4 text-gray-300 font-mono text-xs">{row.model}</td>
              <td className="py-2 px-2 text-right text-gray-400">{row.invocations}</td>
              <td className="py-2 px-2 text-right text-emerald-400">${row.total_cost.toFixed(4)}</td>
              <td className="py-2 pl-2 text-right text-gray-400">${row.avg_cost.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DurationTable({ data }: { data: StatsResult["duration_stats"] }) {
  if (data.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-8" data-testid="duration-stats-empty">
        No duration data yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto" data-testid="duration-stats-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs uppercase border-b border-gray-800">
            <th className="text-left py-2 pr-4">Phase</th>
            <th className="text-right py-2">Avg Duration</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.label} className="border-b border-gray-800/50">
              <td className="py-2 pr-4 text-gray-300">{row.label}</td>
              <td className="py-2 text-right text-gray-400">
                {formatDuration(row.avg_duration_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewLoopSummary({ data }: { data: StatsResult["review_loop"] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="review-loop-summary">
      <MiniStat label="Avg Review Rounds" value={data.avg_review_rounds.toFixed(1)} />
      <MiniStat
        label="First-Pass Approval"
        value={`${(data.first_pass_approval_rate * 100).toFixed(0)}%`}
        color={data.first_pass_approval_rate >= 0.5 ? "text-emerald-400" : "text-yellow-400"}
      />
      <MiniStat label="Total Reviews" value={String(data.total_review_rounds)} />
      <MiniStat label="Total Fix Iters" value={String(data.total_fix_iterations)} />
    </div>
  );
}

function MiniStat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-semibold ${color ?? "text-gray-200"}`}>{value}</div>
    </div>
  );
}
