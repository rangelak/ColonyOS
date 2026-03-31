import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { PhaseCostRow, PhaseFailureRow } from "../types";

interface PhaseCostChartProps {
  data: PhaseCostRow[];
}

export function PhaseCostChart({ data }: PhaseCostChartProps) {
  if (data.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-8" data-testid="phase-cost-chart-empty">
        No phase cost data available yet.
      </div>
    );
  }

  return (
    <div data-testid="phase-cost-chart">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="phase"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            stroke="#4b5563"
          />
          <YAxis
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            stroke="#4b5563"
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: "6px",
              color: "#f3f4f6",
              fontSize: 12,
            }}
            formatter={(value: unknown, name: unknown) => {
              const v = Number(value);
              if (name === "avg_cost") return [`$${v.toFixed(4)}`, "Avg Cost"];
              return [`$${v.toFixed(4)}`, "Total Cost"];
            }}
          />
          <Bar dataKey="total_cost" fill="#34d399" radius={[4, 4, 0, 0]} name="total_cost" />
          <Bar dataKey="avg_cost" fill="#60a5fa" radius={[4, 4, 0, 0]} name="avg_cost" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

interface FailureHotspotsChartProps {
  data: PhaseFailureRow[];
}

export function FailureHotspotsChart({ data }: FailureHotspotsChartProps) {
  if (data.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-8" data-testid="failure-chart-empty">
        No failure data available yet.
      </div>
    );
  }

  const chartData = data.map((row) => ({
    ...row,
    failure_pct: row.failure_rate * 100,
  }));

  return (
    <div data-testid="failure-chart">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="phase"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            stroke="#4b5563"
          />
          <YAxis
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            stroke="#4b5563"
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: "6px",
              color: "#f3f4f6",
              fontSize: 12,
            }}
            formatter={(value: unknown, name: unknown) => {
              const v = Number(value);
              if (name === "failure_pct") return [`${v.toFixed(1)}%`, "Failure Rate"];
              return [v, name === "failures" ? "Failures" : "Executions"];
            }}
          />
          <Bar dataKey="failure_pct" fill="#f87171" radius={[4, 4, 0, 0]} name="failure_pct" />
          <Bar dataKey="failures" fill="#fbbf24" radius={[4, 4, 0, 0]} name="failures" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
