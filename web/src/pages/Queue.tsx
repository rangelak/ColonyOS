import { useState, useEffect, useRef, useCallback } from "react";
import { fetchQueue } from "../api";
import type { QueueState } from "../types";
import QueueTable from "../components/QueueTable";

const POLL_INTERVAL_MS = 5000;

const STATUS_TABS = ["all", "pending", "running", "completed", "failed"] as const;
type StatusTab = (typeof STATUS_TABS)[number];

export default function Queue() {
  const [queue, setQueue] = useState<QueueState | null>(null);
  const [error, setError] = useState(false);
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const q = await fetchQueue();
      setQueue(q);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll]);

  const filteredItems =
    queue?.items.filter((item) =>
      activeTab === "all" ? true : item.status === activeTab
    ) ?? [];

  const aggregateCost = queue?.aggregate_cost_usd ?? 0;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Queue</h1>
          <p className="text-sm text-gray-500 mt-1">
            {queue
              ? `${queue.items.length} item${queue.items.length !== 1 ? "s" : ""} · Total cost: $${aggregateCost.toFixed(2)}`
              : "Loading…"}
          </p>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="px-4 py-3 rounded bg-red-900/20 border border-red-800/30 text-red-300 text-sm">
          Failed to load queue data. Retrying…
        </div>
      )}

      {/* Empty queue state */}
      {!error && queue === null && !error && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg">No queue active</p>
          <p className="text-sm mt-1">The daemon has no active queue session.</p>
        </div>
      )}

      {/* Queue content */}
      {queue && (
        <>
          {/* Status filter tabs */}
          <div className="flex gap-1 border-b border-gray-800 pb-0">
            {STATUS_TABS.map((tab) => {
              const count =
                tab === "all"
                  ? queue.items.length
                  : queue.items.filter((i) => i.status === tab).length;
              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-3 py-2 text-sm font-medium rounded-t transition-colors ${
                    activeTab === tab
                      ? "bg-gray-800 text-gray-100 border-b-2 border-emerald-400"
                      : "text-gray-500 hover:text-gray-300 hover:bg-gray-800/50"
                  }`}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  {count > 0 && (
                    <span className="ml-1.5 text-xs text-gray-500">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Queue table */}
          <QueueTable items={filteredItems} />
        </>
      )}
    </div>
  );
}
