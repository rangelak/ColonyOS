import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { RecentRunEntry } from "../types";

interface CostChartProps {
  data: RecentRunEntry[];
}

export default function CostChart({ data }: CostChartProps) {
  if (data.length === 0) {
    return (
      <div className="text-gray-500 text-sm text-center py-8" data-testid="cost-chart-empty">
        No cost data available yet.
      </div>
    );
  }

  const chartData = data.map((entry, i) => ({
    index: i + 1,
    run_id: entry.run_id.slice(0, 8),
    cost: entry.cost_usd,
    status: entry.status,
  }));

  return (
    <div data-testid="cost-chart">
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="run_id"
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
            formatter={(value: number) => [`$${value.toFixed(4)}`, "Cost"]}
            labelFormatter={(label: string) => `Run: ${label}`}
          />
          <Area
            type="monotone"
            dataKey="cost"
            stroke="#34d399"
            strokeWidth={2}
            fill="url(#costGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
