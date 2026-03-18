"""Aggregate analytics dashboard for ColonyOS run logs.

Structured as two layers:
1. Data layer: Pure functions that load, filter, and compute aggregates,
   returning typed dataclasses.
2. Rendering layer: Functions that take computed dataclasses and render
   them using rich Tables/Panels.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from colonyos.ui import _format_duration

# ---------------------------------------------------------------------------
# Data models (dataclasses for computed aggregates)
# ---------------------------------------------------------------------------


@dataclass
class RunSummary:
    """FR-1: High-level run statistics."""

    total_runs: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    total_cost_usd: float = 0.0


@dataclass
class PhaseCostRow:
    """FR-2: One row in the cost breakdown table."""

    phase: str = ""
    total_cost: float = 0.0
    avg_cost: float = 0.0
    pct_of_total: float = 0.0


@dataclass
class PhaseFailureRow:
    """FR-3: One row in the failure hotspots table."""

    phase: str = ""
    executions: int = 0
    failures: int = 0
    failure_rate: float = 0.0


@dataclass
class ReviewLoopStats:
    """FR-4: Review loop efficiency metrics."""

    avg_review_rounds: float = 0.0
    first_pass_approval_rate: float = 0.0
    total_review_rounds: int = 0
    total_fix_iterations: int = 0


@dataclass
class DurationRow:
    """FR-5: Average duration for a phase or overall."""

    label: str = ""
    avg_duration_ms: int = 0


@dataclass
class RecentRunEntry:
    """FR-6: One entry in the recent trend timeline."""

    run_id: str = ""
    status: str = ""
    cost_usd: float = 0.0


@dataclass
class PhaseDetailRow:
    """Per-run detail for --phase filter."""

    run_id: str = ""
    cost_usd: float | None = None
    duration_ms: int = 0
    success: bool = True


@dataclass
class StatsResult:
    """Top-level container for all computed stats sections."""

    summary: RunSummary = field(default_factory=RunSummary)
    cost_breakdown: list[PhaseCostRow] = field(default_factory=list)
    failure_hotspots: list[PhaseFailureRow] = field(default_factory=list)
    review_loop: ReviewLoopStats = field(default_factory=ReviewLoopStats)
    duration_stats: list[DurationRow] = field(default_factory=list)
    recent_trend: list[RecentRunEntry] = field(default_factory=list)
    phase_detail: list[PhaseDetailRow] = field(default_factory=list)
    phase_filter: str | None = None


# ---------------------------------------------------------------------------
# Data layer: loading, filtering, computation
# ---------------------------------------------------------------------------


def load_run_logs(runs_dir: Path) -> list[dict]:
    """Load all run-*.json files from the runs directory.

    Skips loop_state_*.json files and corrupted JSON files (with a
    stderr warning). Returns list sorted by started_at descending.
    """
    if not runs_dir.exists():
        return []

    results: list[dict] = []
    for f in runs_dir.glob("run-*.json"):
        if f.name.startswith("loop_state_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: skipping corrupted file {f.name}: {exc}", file=sys.stderr)

    results.sort(key=lambda d: d.get("started_at", ""), reverse=True)
    return results


def filter_runs(
    runs: list[dict],
    last: int | None = None,
    phase: str | None = None,
) -> list[dict]:
    """Apply --last N slicing. Phase filtering is handled at compute time."""
    if last is not None and last > 0:
        return runs[:last]
    return runs


def compute_run_summary(runs: list[dict]) -> RunSummary:
    """FR-1: Compute aggregate run statistics."""
    if not runs:
        return RunSummary()

    total = len(runs)
    completed = sum(1 for r in runs if r.get("status") == "completed")
    failed = sum(1 for r in runs if r.get("status") == "failed")
    in_progress = sum(1 for r in runs if r.get("status") == "running")
    total_cost = sum(r.get("total_cost_usd", 0) or 0 for r in runs)

    return RunSummary(
        total_runs=total,
        completed=completed,
        failed=failed,
        in_progress=in_progress,
        success_rate=(completed / total * 100) if total > 0 else 0.0,
        failure_rate=(failed / total * 100) if total > 0 else 0.0,
        total_cost_usd=total_cost,
    )


def compute_cost_breakdown(runs: list[dict]) -> list[PhaseCostRow]:
    """FR-2: Per-phase cost breakdown."""
    phase_costs: dict[str, list[float]] = {}

    for run in runs:
        for phase_entry in run.get("phases", []):
            phase_name = phase_entry.get("phase", "")
            cost = phase_entry.get("cost_usd")
            if cost is not None:
                phase_costs.setdefault(phase_name, []).append(cost)

    total_cost = sum(c for costs in phase_costs.values() for c in costs)
    rows = []
    for phase_name, costs in sorted(phase_costs.items()):
        total = sum(costs)
        rows.append(
            PhaseCostRow(
                phase=phase_name,
                total_cost=total,
                avg_cost=total / len(runs) if runs else 0.0,
                pct_of_total=(total / total_cost * 100) if total_cost > 0 else 0.0,
            )
        )
    return rows


def compute_failure_hotspots(runs: list[dict]) -> list[PhaseFailureRow]:
    """FR-3: Per-phase failure rates, sorted by failure rate descending."""
    phase_stats: dict[str, dict[str, int]] = {}

    for run in runs:
        for phase_entry in run.get("phases", []):
            phase_name = phase_entry.get("phase", "")
            stats = phase_stats.setdefault(phase_name, {"executions": 0, "failures": 0})
            stats["executions"] += 1
            if not phase_entry.get("success", True):
                stats["failures"] += 1

    rows = []
    for phase_name, stats in phase_stats.items():
        execs = stats["executions"]
        fails = stats["failures"]
        rows.append(
            PhaseFailureRow(
                phase=phase_name,
                executions=execs,
                failures=fails,
                failure_rate=(fails / execs * 100) if execs > 0 else 0.0,
            )
        )
    rows.sort(key=lambda r: r.failure_rate, reverse=True)
    return rows


def compute_review_loop_stats(runs: list[dict]) -> ReviewLoopStats:
    """FR-4: Review loop efficiency metrics.

    A "review round" is a contiguous block of review phases. The round ends
    when a non-review phase is encountered. First-pass approval means no
    fix phase appears in the run.
    """
    total_rounds = 0
    total_fixes = 0
    first_pass_approvals = 0
    runs_with_reviews = 0

    for run in runs:
        phases = run.get("phases", [])
        phase_names = [p.get("phase", "") for p in phases]

        has_review = any(p == "review" for p in phase_names)
        if not has_review:
            continue

        runs_with_reviews += 1
        has_fix = any(p == "fix" for p in phase_names)
        fix_count = sum(1 for p in phase_names if p == "fix")
        total_fixes += fix_count

        if not has_fix:
            first_pass_approvals += 1

        # Count review rounds: contiguous blocks of "review" phases
        in_review_block = False
        rounds = 0
        for p in phase_names:
            if p == "review":
                if not in_review_block:
                    rounds += 1
                    in_review_block = True
            else:
                in_review_block = False
        total_rounds += rounds

    return ReviewLoopStats(
        avg_review_rounds=(total_rounds / runs_with_reviews) if runs_with_reviews > 0 else 0.0,
        first_pass_approval_rate=(first_pass_approvals / runs_with_reviews * 100) if runs_with_reviews > 0 else 0.0,
        total_review_rounds=total_rounds,
        total_fix_iterations=total_fixes,
    )


def compute_duration_stats(runs: list[dict]) -> list[DurationRow]:
    """FR-5: Average duration per phase and overall."""
    phase_durations: dict[str, list[int]] = {}

    for run in runs:
        for phase_entry in run.get("phases", []):
            phase_name = phase_entry.get("phase", "")
            duration = phase_entry.get("duration_ms", 0)
            phase_durations.setdefault(phase_name, []).append(duration)

    rows = []
    for phase_name in sorted(phase_durations.keys()):
        durations = phase_durations[phase_name]
        avg = sum(durations) // len(durations) if durations else 0
        rows.append(DurationRow(label=phase_name, avg_duration_ms=avg))

    # Overall average run duration
    run_durations = []
    for run in runs:
        started = run.get("started_at")
        finished = run.get("finished_at")
        if started and finished:
            from datetime import datetime, timezone

            try:
                start_dt = datetime.fromisoformat(started)
                end_dt = datetime.fromisoformat(finished)
                delta_ms = int((end_dt - start_dt).total_seconds() * 1000)
                if delta_ms >= 0:
                    run_durations.append(delta_ms)
            except (ValueError, TypeError):
                pass

    if run_durations:
        avg_total = sum(run_durations) // len(run_durations)
        rows.append(DurationRow(label="Total (wall-clock)", avg_duration_ms=avg_total))

    return rows


def compute_recent_trend(runs: list[dict], count: int = 10) -> list[RecentRunEntry]:
    """FR-6: Recent trend timeline entries."""
    recent = runs[:count]
    return [
        RecentRunEntry(
            run_id=r.get("run_id", "?"),
            status=r.get("status", "unknown"),
            cost_usd=r.get("total_cost_usd", 0) or 0,
        )
        for r in recent
    ]


def compute_phase_detail(runs: list[dict], phase_name: str) -> list[PhaseDetailRow]:
    """Per-run detail for a specific phase (--phase filter)."""
    rows = []
    for run in runs:
        for phase_entry in run.get("phases", []):
            if phase_entry.get("phase", "") == phase_name:
                rows.append(
                    PhaseDetailRow(
                        run_id=run.get("run_id", "?"),
                        cost_usd=phase_entry.get("cost_usd"),
                        duration_ms=phase_entry.get("duration_ms", 0),
                        success=phase_entry.get("success", True),
                    )
                )
    return rows


def compute_stats(
    runs: list[dict], phase_filter: str | None = None
) -> StatsResult:
    """Compute all stats sections and return the assembled result."""
    return StatsResult(
        summary=compute_run_summary(runs),
        cost_breakdown=compute_cost_breakdown(runs),
        failure_hotspots=compute_failure_hotspots(runs),
        review_loop=compute_review_loop_stats(runs),
        duration_stats=compute_duration_stats(runs),
        recent_trend=compute_recent_trend(runs),
        phase_detail=compute_phase_detail(runs, phase_filter) if phase_filter else [],
        phase_filter=phase_filter,
    )


# ---------------------------------------------------------------------------
# Rendering layer: rich output
# ---------------------------------------------------------------------------


def render_run_summary(console: Console, summary: RunSummary) -> None:
    """FR-1: Render run summary as a Rich Panel."""
    lines = [
        f"Total Runs:    {summary.total_runs}",
        f"Completed:     {summary.completed}",
        f"Failed:        {summary.failed}",
    ]
    if summary.in_progress > 0:
        lines.append(f"In Progress:   {summary.in_progress}")
    lines.extend([
        f"Success Rate:  {summary.success_rate:.1f}%",
        f"Failure Rate:  {summary.failure_rate:.1f}%",
        f"Total Cost:    ${summary.total_cost_usd:.4f}",
    ])
    console.print(Panel("\n".join(lines), title="Run Summary", border_style="green"))


def render_cost_breakdown(console: Console, rows: list[PhaseCostRow]) -> None:
    """FR-2: Render cost breakdown as a Rich Table."""
    if not rows:
        return
    table = Table(title="Cost Breakdown by Phase")
    table.add_column("Phase", style="cyan")
    table.add_column("Total Cost", justify="right")
    table.add_column("Avg Cost/Run", justify="right")
    table.add_column("% of Total", justify="right")

    for row in rows:
        table.add_row(
            row.phase,
            f"${row.total_cost:.4f}",
            f"${row.avg_cost:.4f}",
            f"{row.pct_of_total:.1f}%",
        )
    console.print(table)


def render_failure_hotspots(console: Console, rows: list[PhaseFailureRow]) -> None:
    """FR-3: Render failure hotspots as a Rich Table."""
    if not rows:
        return
    table = Table(title="Phase Failure Hotspots")
    table.add_column("Phase", style="cyan")
    table.add_column("Executions", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Failure Rate", justify="right")

    for row in rows:
        table.add_row(
            row.phase,
            str(row.executions),
            str(row.failures),
            f"{row.failure_rate:.1f}%",
        )
    console.print(table)


def render_review_loop_stats(console: Console, stats: ReviewLoopStats) -> None:
    """FR-4: Render review loop efficiency as a Rich Panel."""
    lines = [
        f"Avg Review Rounds/Run:    {stats.avg_review_rounds:.1f}",
        f"First-Pass Approval Rate: {stats.first_pass_approval_rate:.1f}%",
        f"Total Review Rounds:      {stats.total_review_rounds}",
        f"Total Fix Iterations:     {stats.total_fix_iterations}",
    ]
    console.print(Panel("\n".join(lines), title="Review Loop Efficiency", border_style="blue"))


def render_duration_stats(console: Console, rows: list[DurationRow]) -> None:
    """FR-5: Render duration stats as a Rich Table."""
    if not rows:
        return
    table = Table(title="Average Duration by Phase")
    table.add_column("Phase", style="cyan")
    table.add_column("Avg Duration", justify="right")

    for row in rows:
        table.add_row(row.label, _format_duration(row.avg_duration_ms))
    console.print(table)


def render_recent_trend(console: Console, entries: list[RecentRunEntry]) -> None:
    """FR-6: Render recent trend as a compact timeline."""
    if not entries:
        return
    parts = []
    for entry in entries:
        symbol = "✓" if entry.status == "completed" else "✗"
        style = "green" if entry.status == "completed" else "red"
        if entry.status == "running":
            symbol = "…"
            style = "yellow"
        parts.append(f"[{style}]{symbol}[/{style}] ${entry.cost_usd:.2f}")

    console.print(Panel("  ".join(parts), title="Recent Runs", border_style="dim"))


def render_phase_detail(
    console: Console, rows: list[PhaseDetailRow], phase_name: str
) -> None:
    """Render per-run detail for a specific phase."""
    if not rows:
        console.print(f"No data for phase: {phase_name}")
        return
    table = Table(title=f"Phase Detail: {phase_name}")
    table.add_column("Run ID", style="cyan")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Status", justify="center")

    for row in rows:
        cost_str = f"${row.cost_usd:.4f}" if row.cost_usd is not None else "—"
        status_str = "[green]✓[/green]" if row.success else "[red]✗[/red]"
        table.add_row(
            row.run_id,
            cost_str,
            _format_duration(row.duration_ms),
            status_str,
        )
    console.print(table)


def render_dashboard(console: Console, result: StatsResult) -> None:
    """Orchestrate rendering of all dashboard sections."""
    render_run_summary(console, result.summary)
    console.print()

    render_cost_breakdown(console, result.cost_breakdown)
    console.print()

    render_failure_hotspots(console, result.failure_hotspots)
    console.print()

    render_review_loop_stats(console, result.review_loop)
    console.print()

    render_duration_stats(console, result.duration_stats)
    console.print()

    render_recent_trend(console, result.recent_trend)

    if result.phase_filter and result.phase_detail:
        console.print()
        render_phase_detail(console, result.phase_detail, result.phase_filter)
