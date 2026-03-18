import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchRun } from "../api";
import type { ShowResult } from "../types";
import PhaseTimeline from "../components/PhaseTimeline";
import { formatDuration, statusColor, statusIcon, formatTimestamp } from "../util";

const POLL_INTERVAL_MS = 5000;

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ShowResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;

    async function load() {
      try {
        const result = await fetchRun(id!);
        if (active) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (active) setError(String(err));
      }
    }

    load();
    // Only poll while run is still in progress
    const timer = setInterval(() => {
      if (data?.header.status === "running") load();
    }, POLL_INTERVAL_MS);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id, data?.header.status]);

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300">
        <p>{error}</p>
        <Link to="/" className="text-emerald-400 hover:underline text-sm mt-2 inline-block">
          Back to dashboard
        </Link>
      </div>
    );
  }

  if (!data) {
    return <p className="text-gray-500">Loading...</p>;
  }

  const h = data.header;

  return (
    <div>
      {/* Breadcrumb */}
      <div className="mb-4">
        <Link to="/" className="text-gray-500 hover:text-gray-300 text-sm">
          Dashboard
        </Link>
        <span className="text-gray-600 mx-2">/</span>
        <span className="text-gray-300 text-sm font-mono">{h.run_id}</span>
      </div>

      {/* Header */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
        <div className="flex items-center gap-3 mb-3">
          <span className={`text-lg font-bold ${statusColor(h.status)}`}>
            {statusIcon(h.status)} {h.status.toUpperCase()}
          </span>
          <span className="font-mono text-sm text-gray-400">{h.run_id}</span>
        </div>
        <p className="text-gray-300 text-sm mb-3">{h.prompt}</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Cost</span>
            <p className="font-mono text-gray-200">${h.total_cost_usd.toFixed(2)}</p>
          </div>
          <div>
            <span className="text-gray-500">Duration</span>
            <p className="text-gray-200">
              {h.wall_clock_ms > 0 ? formatDuration(h.wall_clock_ms) : "-"}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Started</span>
            <p className="text-gray-200">{formatTimestamp(h.started_at)}</p>
          </div>
          {h.branch_name && (
            <div>
              <span className="text-gray-500">Branch</span>
              <p className="text-gray-200 font-mono text-xs">{h.branch_name}</p>
            </div>
          )}
        </div>
        {(h.prd_rel || h.task_rel || h.source_issue_url) && (
          <div className="mt-3 pt-3 border-t border-gray-800 flex gap-4 text-xs">
            {h.prd_rel && (
              <span className="text-gray-400">PRD: <span className="text-gray-300">{h.prd_rel}</span></span>
            )}
            {h.task_rel && (
              <span className="text-gray-400">Tasks: <span className="text-gray-300">{h.task_rel}</span></span>
            )}
            {h.source_issue_url && (
              <a href={h.source_issue_url} className="text-emerald-400 hover:underline" target="_blank" rel="noreferrer">
                Issue
              </a>
            )}
          </div>
        )}
      </div>

      {/* Review summary */}
      {data.review_summary && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Review Summary</h3>
          <div className="flex gap-6 text-sm">
            <div>
              <span className="text-gray-500">Rounds:</span>{" "}
              <span className="text-gray-200">{data.review_summary.review_rounds}</span>
            </div>
            <div>
              <span className="text-gray-500">Fix iterations:</span>{" "}
              <span className="text-gray-200">{data.review_summary.fix_iterations}</span>
            </div>
            {data.has_decision && (
              <div>
                <span className="text-gray-500">Decision:</span>{" "}
                <span className={data.decision_success ? "text-emerald-400" : "text-red-400"}>
                  {data.decision_success ? "Approved" : "Rejected"}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Phase timeline */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">Phase Timeline</h3>
        <PhaseTimeline entries={data.timeline} />
      </div>
    </div>
  );
}
