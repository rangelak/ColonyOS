import { useState, useEffect, useRef, useCallback } from "react";
import { fetchDaemonHealth, fetchHealth, pauseDaemon, resumeDaemon } from "../api";
import { capitalize, healthStatusDot } from "../util";
import type { DaemonHealth } from "../types";

const POLL_INTERVAL_MS = 5000;

export default function DaemonHealthBanner() {
  const [health, setHealth] = useState<DaemonHealth | null>(null);
  const [error, setError] = useState(false);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [confirming, setConfirming] = useState<"pause" | "resume" | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const h = await fetchDaemonHealth();
      setHealth(h);
      setError(false);
    } catch {
      setHealth(null);
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

  // Check write_enabled once on mount
  useEffect(() => {
    fetchHealth()
      .then((h) => setWriteEnabled(h.write_enabled === "true"))
      .catch(() => setWriteEnabled(false));
  }, []);

  const handleAction = async () => {
    if (!confirming) return;
    setActionLoading(true);
    try {
      const updated =
        confirming === "pause" ? await pauseDaemon() : await resumeDaemon();
      setHealth(updated);
    } catch {
      // Silently fail — next poll will update state
    } finally {
      setActionLoading(false);
      setConfirming(null);
    }
  };

  if (error) {
    return (
      <div className="px-3 py-2 rounded bg-gray-800 border border-gray-700">
        <div className="flex items-center gap-2">
          <span
            data-testid="health-dot"
            className="w-2 h-2 rounded-full bg-gray-400 shrink-0"
          />
          <span className="text-xs text-gray-400">Unreachable</span>
        </div>
      </div>
    );
  }

  if (!health) {
    return (
      <div className="px-3 py-2 rounded bg-gray-800 border border-gray-700">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-gray-600 shrink-0 animate-pulse" />
          <span className="text-xs text-gray-500">Loading...</span>
        </div>
      </div>
    );
  }

  const totalBudget = health.daily_spend_usd + health.daily_budget_remaining_usd;
  const spendPct = totalBudget > 0 ? (health.daily_spend_usd / totalBudget) * 100 : 0;

  return (
    <div className="px-3 py-2 rounded bg-gray-800 border border-gray-700 space-y-2">
      {/* Status row */}
      <div className="flex items-center gap-2">
        <span
          data-testid="health-dot"
          className={`w-2 h-2 rounded-full shrink-0 ${healthStatusDot(health.status)}`}
        />
        <span className="text-xs font-medium text-gray-200">
          {capitalize(health.status)}
        </span>
        <span className="text-xs text-gray-500 ml-auto">
          Q: {health.queue_depth}
        </span>
      </div>

      {/* Budget bar */}
      <div>
        <div className="flex justify-between text-[10px] text-gray-400 mb-0.5">
          <span>${health.daily_spend_usd.toFixed(2)}</span>
          <span>${totalBudget.toFixed(2)}</span>
        </div>
        <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              spendPct > 90
                ? "bg-red-400"
                : spendPct > 70
                  ? "bg-yellow-400"
                  : "bg-emerald-400"
            }`}
            style={{ width: `${Math.min(spendPct, 100)}%` }}
          />
        </div>
      </div>

      {/* Warnings */}
      {health.circuit_breaker_active && (
        <div className="text-[10px] text-red-400 font-medium">
          Circuit breaker active
        </div>
      )}
      {health.paused && (
        <div className="text-[10px] text-yellow-400 font-medium">
          Daemon paused
        </div>
      )}
      {health.consecutive_failures > 0 && !health.circuit_breaker_active && (
        <div className="text-[10px] text-yellow-400">
          {health.consecutive_failures} consecutive failure{health.consecutive_failures !== 1 ? "s" : ""}
        </div>
      )}

      {/* Pause/Resume button */}
      {writeEnabled && (
        <div>
          {confirming ? (
            <div className="space-y-1">
              <p className="text-[10px] text-gray-300">
                Are you sure you want to {confirming} the daemon?
              </p>
              <div className="flex gap-1">
                <button
                  onClick={handleAction}
                  disabled={actionLoading}
                  className={`text-[10px] px-2 py-0.5 rounded font-medium ${
                    confirming === "pause"
                      ? "bg-yellow-400/20 text-yellow-400 hover:bg-yellow-400/30"
                      : "bg-emerald-400/20 text-emerald-400 hover:bg-emerald-400/30"
                  } disabled:opacity-50`}
                >
                  {actionLoading ? "..." : "Confirm"}
                </button>
                <button
                  onClick={() => setConfirming(null)}
                  className="text-[10px] px-2 py-0.5 rounded text-gray-400 hover:text-gray-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() =>
                setConfirming(health.paused ? "resume" : "pause")
              }
              className={`text-[10px] px-2 py-0.5 rounded font-medium w-full ${
                health.paused
                  ? "bg-emerald-400/20 text-emerald-400 hover:bg-emerald-400/30"
                  : "bg-yellow-400/20 text-yellow-400 hover:bg-yellow-400/30"
              }`}
            >
              {health.paused ? "Resume" : "Pause"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
