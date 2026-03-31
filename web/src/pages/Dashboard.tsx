import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRuns, fetchStats, fetchHealth, fetchDaemonHealth, fetchQueue } from "../api";
import type { RunLog, StatsResult, DaemonHealth, QueueState } from "../types";
import StatsPanel from "../components/StatsPanel";
import RunList from "../components/RunList";
import RunLauncher from "../components/RunLauncher";
import { capitalize, healthStatusDot } from "../util";

const POLL_INTERVAL_MS = 5000;

function HealthSummaryCard({ health }: { health: DaemonHealth }) {
  const totalBudget = health.daily_spend_usd + health.daily_budget_remaining_usd;
  const spendPct = totalBudget > 0 ? (health.daily_spend_usd / totalBudget) * 100 : 0;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">Daemon Health</h3>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${healthStatusDot(health.status)}`} />
          <span className="text-sm font-medium text-gray-200">{capitalize(health.status)}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div>
          <p className="text-xs text-gray-500">Daily Spend</p>
          <p className="text-gray-200 font-mono">${health.daily_spend_usd.toFixed(2)} / ${totalBudget.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Queue Depth</p>
          <p className="text-gray-200">{health.queue_depth}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Items Today</p>
          <p className="text-gray-200">{health.total_items_today}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Failures</p>
          <p className={health.consecutive_failures > 0 ? "text-yellow-400" : "text-gray-200"}>
            {health.consecutive_failures}
          </p>
        </div>
      </div>
      {/* Budget bar */}
      <div className="mt-3">
        <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              spendPct > 90 ? "bg-red-400" : spendPct > 70 ? "bg-yellow-400" : "bg-emerald-400"
            }`}
            style={{ width: `${Math.min(spendPct, 100)}%` }}
          />
        </div>
      </div>
      {/* Warnings */}
      {health.circuit_breaker_active && (
        <p className="mt-2 text-xs text-red-400 font-medium">Circuit breaker active</p>
      )}
      {health.paused && (
        <p className="mt-2 text-xs text-yellow-400 font-medium">Daemon paused</p>
      )}
    </div>
  );
}

function QueueSummaryCard({ queue }: { queue: QueueState }) {
  const pending = queue.items.filter((i) => i.status === "pending").length;
  const running = queue.items.filter((i) => i.status === "running").length;
  const runningItem = queue.items.find((i) => i.status === "running");

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">Queue</h3>
        <Link to="/queue" className="text-xs text-emerald-400 hover:text-emerald-300">
          View all →
        </Link>
      </div>
      <div className="flex gap-4 text-sm">
        <div>
          <span className="text-yellow-400 font-medium">{pending} pending</span>
        </div>
        <div>
          <span className="text-blue-400 font-medium">{running} running</span>
        </div>
        <div>
          <span className="text-gray-400">{queue.items.length} total</span>
        </div>
      </div>
      {runningItem && (
        <div className="mt-2 text-xs text-gray-400 truncate">
          <span className="text-blue-400">▶</span>{" "}
          {runningItem.source_value}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [runs, setRuns] = useState<RunLog[]>([]);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [daemonHealth, setDaemonHealth] = useState<DaemonHealth | null>(null);
  const [queue, setQueue] = useState<QueueState | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((h) => setWriteEnabled(h.write_enabled === "true"))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [r, s] = await Promise.all([fetchRuns(), fetchStats()]);
        if (active) {
          setRuns(r);
          setStats(s);
          setError(null);
        }
      } catch (err) {
        if (active) setError(String(err));
      }

      // Load daemon health and queue (non-blocking)
      try {
        const h = await fetchDaemonHealth();
        if (active) setDaemonHealth(h);
      } catch {
        // Daemon may not be running
      }

      try {
        const q = await fetchQueue();
        if (active) setQueue(q);
      } catch {
        // Queue endpoint may not be available
      }
    }

    load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-100 mb-4">Dashboard</h2>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 mb-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Health + Queue summary row */}
      {(daemonHealth || queue) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {daemonHealth && <HealthSummaryCard health={daemonHealth} />}
          {queue && <QueueSummaryCard queue={queue} />}
        </div>
      )}

      {writeEnabled && <RunLauncher />}
      {stats && <StatsPanel summary={stats.summary} reviewLoop={stats.review_loop} />}
      <RunList runs={runs} />
    </div>
  );
}
