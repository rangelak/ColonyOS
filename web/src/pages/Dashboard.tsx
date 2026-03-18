import { useEffect, useState } from "react";
import { fetchRuns, fetchStats } from "../api";
import type { RunLog, StatsResult } from "../types";
import StatsPanel from "../components/StatsPanel";
import RunList from "../components/RunList";

const POLL_INTERVAL_MS = 5000;

export default function Dashboard() {
  const [runs, setRuns] = useState<RunLog[]>([]);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [error, setError] = useState<string | null>(null);

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

      {stats && <StatsPanel summary={stats.summary} />}
      <RunList runs={runs} />
    </div>
  );
}
