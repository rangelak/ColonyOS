import { useState, useMemo } from "react";
import { CheckCircle, XCircle, SkipForward, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import type { PhaseTimelineEntry } from "../types";
import { formatDuration } from "../util";

function PhaseIcon({ entry }: { entry: PhaseTimelineEntry }) {
  if (entry.is_skipped) {
    return <SkipForward className="w-5 h-5 text-gray-500 shrink-0" />;
  }
  return entry.success ? (
    <CheckCircle className="w-5 h-5 text-emerald-400 shrink-0" />
  ) : (
    <XCircle className="w-5 h-5 text-red-400 shrink-0" />
  );
}

/** Check if a phase name indicates a review/fix loop phase. */
function isLoopPhase(phase: string): boolean {
  const lower = phase.toLowerCase();
  return lower.includes("review") || lower.includes("fix");
}

interface LoopGroup {
  kind: "loop";
  entries: { entry: PhaseTimelineEntry; originalIndex: number }[];
}

interface SingleEntry {
  kind: "single";
  entry: PhaseTimelineEntry;
  originalIndex: number;
}

type TimelineItem = LoopGroup | SingleEntry;

/**
 * Group consecutive review/fix phases into loop groups.
 * Non-loop phases become single entries.
 */
function groupEntries(entries: PhaseTimelineEntry[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  let currentLoop: LoopGroup | null = null;

  entries.forEach((entry, idx) => {
    if (isLoopPhase(entry.phase)) {
      if (!currentLoop) {
        currentLoop = { kind: "loop", entries: [] };
      }
      currentLoop.entries.push({ entry, originalIndex: idx });
    } else {
      if (currentLoop) {
        // Only group if there are 2+ review/fix entries
        if (currentLoop.entries.length >= 2) {
          items.push(currentLoop);
        } else {
          // Single loop phase — render as a regular entry
          for (const e of currentLoop.entries) {
            items.push({ kind: "single", entry: e.entry, originalIndex: e.originalIndex });
          }
        }
        currentLoop = null;
      }
      items.push({ kind: "single", entry, originalIndex: idx });
    }
  });

  // Flush remaining loop group
  if (currentLoop) {
    if (currentLoop.entries.length >= 2) {
      items.push(currentLoop);
    } else {
      for (const e of currentLoop.entries) {
        items.push({ kind: "single", entry: e.entry, originalIndex: e.originalIndex });
      }
    }
  }

  return items;
}

function PhaseRow({
  entry,
  index,
  maxDuration,
  expandedErrors,
  toggleError,
  isLast,
  showConnector,
}: {
  entry: PhaseTimelineEntry;
  index: number;
  maxDuration: number;
  expandedErrors: Set<number>;
  toggleError: (idx: number) => void;
  isLast: boolean;
  showConnector: boolean;
}) {
  const durationPct = maxDuration > 0 ? (entry.duration_ms / maxDuration) * 100 : 0;
  const isExpanded = expandedErrors.has(index);

  return (
    <div className="relative">
      <div className="flex items-start gap-3 py-2 px-3 rounded hover:bg-gray-800/40 transition-colors">
        {/* Icon column with connector */}
        <div className="relative flex flex-col items-center">
          <PhaseIcon entry={entry} />
          {showConnector && !isLast && (
            <div
              data-testid="timeline-connector"
              className="w-0.5 bg-gray-700 flex-1 min-h-[16px] mt-1"
            />
          )}
        </div>

        {/* Phase details */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-200 text-sm">
              {entry.phase}
            </span>
            {entry.model && (
              <span className="text-xs bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                {entry.model}
              </span>
            )}
            {entry.is_collapsed && (
              <span className="text-xs text-gray-500">
                ({entry.collapsed_count} reviews)
              </span>
            )}
          </div>

          {/* Duration bar */}
          <div className="mt-1.5 h-1.5 bg-gray-800 rounded-full overflow-hidden max-w-[200px]">
            <div
              data-testid="duration-bar"
              className={`h-full rounded-full transition-all ${
                entry.is_skipped
                  ? "bg-gray-600"
                  : entry.success
                    ? "bg-emerald-500/60"
                    : "bg-red-500/60"
              }`}
              style={{ width: `${durationPct}%` }}
            />
          </div>

          {/* Error details */}
          {entry.error && (
            <div className="mt-1">
              <button
                data-testid={`error-toggle-${index}`}
                onClick={() => toggleError(index)}
                className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown className="w-3 h-3" />
                ) : (
                  <ChevronRight className="w-3 h-3" />
                )}
                Error details
              </button>
              <p
                data-testid={`phase-error-${index}`}
                className={`text-xs text-red-400 mt-0.5 ${isExpanded ? "" : "line-clamp-1"}`}
              >
                {entry.error}
              </p>
            </div>
          )}
        </div>

        {/* Cost & duration */}
        <div className="text-right text-xs text-gray-500 shrink-0">
          {entry.cost_usd != null && (
            <div className="font-mono">${entry.cost_usd.toFixed(2)}</div>
          )}
          {entry.duration_ms > 0 && (
            <div>{formatDuration(entry.duration_ms)}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PhaseTimeline({
  entries,
}: {
  entries: PhaseTimelineEntry[];
}) {
  const [expandedErrors, setExpandedErrors] = useState<Set<number>>(new Set());

  const maxDuration = useMemo(
    () => Math.max(...entries.map((e) => e.duration_ms), 0),
    [entries],
  );

  const groupedItems = useMemo(() => groupEntries(entries), [entries]);

  const toggleError = (idx: number) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  if (entries.length === 0) {
    return <p className="text-gray-500 text-sm">No phases recorded.</p>;
  }

  // Count total visible items for connector logic
  let visibleIndex = 0;
  const totalVisible = groupedItems.reduce(
    (acc, item) => acc + (item.kind === "loop" ? item.entries.length : 1),
    0,
  );

  return (
    <div className="space-y-0">
      {groupedItems.map((item, groupIdx) => {
        if (item.kind === "single") {
          const isLast = visibleIndex === totalVisible - 1;
          const row = (
            <PhaseRow
              key={`single-${item.originalIndex}`}
              entry={item.entry}
              index={item.originalIndex}
              maxDuration={maxDuration}
              expandedErrors={expandedErrors}
              toggleError={toggleError}
              isLast={isLast}
              showConnector={true}
            />
          );
          visibleIndex++;
          return row;
        }

        // Loop group
        const loopNode = (
          <div
            key={`loop-${groupIdx}`}
            data-testid="loop-group"
            className="relative ml-2 border-l-2 border-dashed border-gray-700 pl-2 my-1"
          >
            {/* Loop header */}
            <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1 -ml-[11px]">
              <RefreshCw className="w-3.5 h-3.5 text-gray-500" />
              <span>Review/Fix Loop ({Math.ceil(item.entries.length / 2)} iteration{Math.ceil(item.entries.length / 2) !== 1 ? "s" : ""})</span>
            </div>
            {item.entries.map(({ entry, originalIndex }, loopIdx) => {
              const isLastInLoop = loopIdx === item.entries.length - 1;
              const isLastOverall = visibleIndex === totalVisible - 1;
              const row = (
                <PhaseRow
                  key={`loop-entry-${originalIndex}`}
                  entry={entry}
                  index={originalIndex}
                  maxDuration={maxDuration}
                  expandedErrors={expandedErrors}
                  toggleError={toggleError}
                  isLast={isLastOverall}
                  showConnector={!isLastInLoop}
                />
              );
              visibleIndex++;
              return row;
            })}
          </div>
        );
        return loopNode;
      })}
    </div>
  );
}
