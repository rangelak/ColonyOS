"""Single-run inspector for ColonyOS run logs.

Structured as two layers following the stats.py pattern:
1. Data layer: Pure functions that resolve, load, and compute run details,
   returning typed dataclasses.
2. Rendering layer: Functions that take computed dataclasses and render
   them using rich Panels/Tables.
"""

from __future__ import annotations

import json
import re
from typing import cast
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _format_duration_ms(ms: int) -> str:
    secs = ms // 1000
    if secs < 60:
        return f"{secs}s"
    mins, rem = divmod(secs, 60)
    return f"{mins}m {rem}s"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RunHeader:
    """FR-2: Metadata for the run header panel."""

    run_id: str = ""
    status: str = "unknown"
    branch_name: str | None = None
    total_cost_usd: float = 0.0
    started_at: str = ""
    finished_at: str | None = None
    wall_clock_ms: int = 0
    prompt: str = ""
    prompt_truncated: str = ""
    source_issue_url: str | None = None
    last_successful_phase: str | None = None
    prd_rel: str | None = None
    task_rel: str | None = None


@dataclass
class PhaseTimelineEntry:
    """FR-3: One row in the phase timeline (may represent a collapsed group)."""

    phase: str = ""
    model: str | None = None
    duration_ms: int = 0
    cost_usd: float | None = None
    success: bool = True
    is_collapsed: bool = False
    collapsed_count: int = 1
    round_number: int | None = None
    session_id: str = ""
    error: str | None = None
    is_skipped: bool = False


@dataclass
class ReviewSummary:
    """FR-4: Computed review statistics."""

    review_rounds: int = 0
    fix_iterations: int = 0
    per_round_review_counts: list[int] = field(default_factory=list)


@dataclass
class ShowResult:
    """Top-level container for all computed sections."""

    header: RunHeader = field(default_factory=RunHeader)
    timeline: list[PhaseTimelineEntry] = field(default_factory=list)
    review_summary: ReviewSummary | None = None
    has_decision: bool = False
    decision_success: bool = False
    has_ci_fix: bool = False
    ci_fix_attempts: int = 0
    ci_fix_final_success: bool = False
    phase_filter: str | None = None
    phase_detail: list[PhaseTimelineEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data layer: resolution, loading, computation
# ---------------------------------------------------------------------------

_UNSAFE_PATTERN = re.compile(r"[/\\]|\.\.")


def _json_str(v: object, default: str = "") -> str:
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def _json_str_optional(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


def _json_float(v: object, default: float = 0.0) -> float:
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return default
    return default


def _json_float_optional(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _json_int(v: object, default: int = 0) -> int:
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(v.strip()))
        except ValueError:
            return default
    return default


def _json_bool(v: object, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    return default


def _as_phase_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, object]] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            out.append(cast(dict[str, object], item))
    return out


def validate_run_id_input(partial_id: str) -> None:
    """Reject inputs that could cause path traversal.

    Raises ValueError if the input contains '/', '\\', or '..'.
    """
    if _UNSAFE_PATTERN.search(partial_id):
        raise ValueError(
            f"Invalid run ID {partial_id!r}: must not contain '/', '\\\\', or '..'"
        )


def resolve_run_id(runs_dir: Path, partial_id: str) -> str | list[str]:
    """Resolve a partial run ID to a unique run file.

    Returns:
        str: The unique matching run ID.
        list[str]: A list of ambiguous matches (2+).

    Raises:
        FileNotFoundError: If zero matches found.
        ValueError: If input contains path traversal characters.
    """
    validate_run_id_input(partial_id)

    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")

    matches: list[str] = []
    for f in sorted(runs_dir.glob("run-*.json")):
        run_id = f.stem  # e.g. "run-20260317_163656-007cdfc1b9"
        # Match by prefix on the full run ID
        if run_id.startswith(partial_id) or run_id == partial_id:
            matches.append(run_id)
        # Match by hash suffix (the part after the last dash)
        elif partial_id in run_id:
            matches.append(run_id)

    if len(matches) == 0:
        raise FileNotFoundError(f"No run found matching {partial_id!r}")
    if len(matches) == 1:
        return matches[0]
    return matches


def load_single_run(runs_dir: Path, run_id: str) -> dict[str, object]:
    """Load a single run JSON file by run ID.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    file_path = runs_dir / f"{run_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Run file not found: {file_path}")
    return cast(
        dict[str, object],
        json.loads(file_path.read_text(encoding="utf-8")),
    )


def _compute_wall_clock_ms(started_at: str, finished_at: str | None) -> int:
    """Compute wall-clock duration in milliseconds between two ISO timestamps."""
    if not started_at or not finished_at:
        return 0
    try:
        start_dt = datetime.fromisoformat(started_at)
        end_dt = datetime.fromisoformat(finished_at)
        delta_ms = int((end_dt - start_dt).total_seconds() * 1000)
        return max(delta_ms, 0)
    except (ValueError, TypeError):
        return 0


def _truncate_prompt(prompt: str, max_len: int = 120) -> str:
    """Truncate a prompt string, adding ellipsis if needed."""
    if len(prompt) <= max_len:
        return prompt
    return prompt[:max_len - 3] + "..."


def compute_run_header(run_data: dict[str, object]) -> RunHeader:
    """FR-2: Extract metadata for the run header panel."""
    started_at = _json_str(run_data.get("started_at", ""))
    finished_at = _json_str_optional(run_data.get("finished_at"))
    prompt = _json_str(run_data.get("prompt", ""))
    raw_cost = run_data.get("total_cost_usd", 0) or 0

    return RunHeader(
        run_id=_json_str(run_data.get("run_id", "?")),
        status=_json_str(run_data.get("status", "unknown")),
        branch_name=_json_str_optional(run_data.get("branch_name")),
        total_cost_usd=_json_float(raw_cost, 0.0),
        started_at=started_at,
        finished_at=finished_at,
        wall_clock_ms=_compute_wall_clock_ms(started_at, finished_at),
        prompt=prompt,
        prompt_truncated=_truncate_prompt(prompt),
        source_issue_url=_json_str_optional(run_data.get("source_issue_url")),
        last_successful_phase=_json_str_optional(
            run_data.get("last_successful_phase")
        ),
        prd_rel=_json_str_optional(run_data.get("prd_rel")),
        task_rel=_json_str_optional(run_data.get("task_rel")),
    )


def collapse_phase_timeline(
    phases: list[dict[str, object]],
) -> list[PhaseTimelineEntry]:
    """FR-3: Build a timeline with contiguous review phases collapsed.

    Review phases that appear contiguously are collapsed into a single
    summary entry. A 'fix' phase starts a new round.
    """
    if not phases:
        return []

    entries: list[PhaseTimelineEntry] = []
    round_number = 0
    i = 0

    while i < len(phases):
        phase_entry = phases[i]
        phase_name = _json_str(phase_entry.get("phase", ""))

        if phase_name == "review":
            # Collect contiguous review phases
            round_number += 1
            contiguous_reviews: list[dict[str, object]] = []
            while i < len(phases) and phases[i].get("phase", "") == "review":
                contiguous_reviews.append(phases[i])
                i += 1

            total_cost = sum(
                _json_float(p.get("cost_usd", 0) or 0, 0.0)
                for p in contiguous_reviews
            )
            total_duration = sum(
                _json_int(p.get("duration_ms", 0), 0)
                for p in contiguous_reviews
            )
            all_success = all(
                _json_bool(p.get("success", True), True)
                for p in contiguous_reviews
            )

            if len(contiguous_reviews) == 1:
                first_rev = contiguous_reviews[0]
                entries.append(
                    PhaseTimelineEntry(
                        phase="review",
                        model=_json_str_optional(first_rev.get("model")),
                        duration_ms=total_duration,
                        cost_usd=total_cost,
                        success=all_success,
                        is_collapsed=False,
                        collapsed_count=1,
                        round_number=round_number,
                        session_id=_json_str(first_rev.get("session_id", "")),
                        error=_json_str_optional(first_rev.get("error")),
                    )
                )
            else:
                entries.append(
                    PhaseTimelineEntry(
                        phase=f"review x{len(contiguous_reviews)}",
                        duration_ms=total_duration,
                        cost_usd=total_cost,
                        success=all_success,
                        is_collapsed=True,
                        collapsed_count=len(contiguous_reviews),
                        round_number=round_number,
                    )
                )
        elif phase_name == "fix":
            entries.append(
                PhaseTimelineEntry(
                    phase="fix",
                    model=_json_str_optional(phase_entry.get("model")),
                    duration_ms=_json_int(phase_entry.get("duration_ms", 0), 0),
                    cost_usd=_json_float_optional(phase_entry.get("cost_usd")),
                    success=_json_bool(phase_entry.get("success", True), True),
                    session_id=_json_str(phase_entry.get("session_id", "")),
                    error=_json_str_optional(phase_entry.get("error")),
                )
            )
            i += 1
        else:
            entries.append(
                PhaseTimelineEntry(
                    phase=phase_name,
                    model=_json_str_optional(phase_entry.get("model")),
                    duration_ms=_json_int(phase_entry.get("duration_ms", 0), 0),
                    cost_usd=_json_float_optional(phase_entry.get("cost_usd")),
                    success=_json_bool(phase_entry.get("success", True), True),
                    session_id=_json_str(phase_entry.get("session_id", "")),
                    error=_json_str_optional(phase_entry.get("error")),
                )
            )
            i += 1

    return entries


def compute_review_summary(phases: list[dict[str, object]]) -> ReviewSummary | None:
    """FR-4: Compute review statistics from phase list.

    Returns None if no review phases exist.
    """
    phase_names = [_json_str(p.get("phase", "")) for p in phases]
    if "review" not in phase_names:
        return None

    review_rounds = 0
    fix_iterations = sum(1 for p in phase_names if p == "fix")
    per_round_counts: list[int] = []

    in_review_block = False
    current_count = 0

    for name in phase_names:
        if name == "review":
            if not in_review_block:
                review_rounds += 1
                in_review_block = True
                current_count = 0
            current_count += 1
        else:
            if in_review_block:
                per_round_counts.append(current_count)
                in_review_block = False

    # Handle case where reviews are at the end
    if in_review_block:
        per_round_counts.append(current_count)

    return ReviewSummary(
        review_rounds=review_rounds,
        fix_iterations=fix_iterations,
        per_round_review_counts=per_round_counts,
    )


def compute_show_result(
    run_data: dict[str, object], phase_filter: str | None = None
) -> ShowResult:
    """Assemble all computed sections into a ShowResult."""
    phases = _as_phase_dict_list(run_data.get("phases", []))
    phase_names = [_json_str(p.get("phase", "")) for p in phases]

    header = compute_run_header(run_data)
    timeline = collapse_phase_timeline(phases)
    review_summary = compute_review_summary(phases)

    # Decision gate
    has_decision = "decision" in phase_names
    decision_success = False
    if has_decision:
        decision_phases = [
            p for p in phases if _json_str(p.get("phase", "")) == "decision"
        ]
        decision_success = all(
            _json_bool(p.get("success", True), True) for p in decision_phases
        )

    # CI fix
    ci_fix_phases = [
        p for p in phases if _json_str(p.get("phase", "")) == "ci_fix"
    ]
    has_ci_fix = len(ci_fix_phases) > 0
    ci_fix_final_success = (
        _json_bool(ci_fix_phases[-1].get("success", False), False)
        if ci_fix_phases
        else False
    )

    # Phase detail for --phase filter
    phase_detail: list[PhaseTimelineEntry] = []
    if phase_filter:
        for _, p in enumerate(phases):
            if _json_str(p.get("phase", "")) == phase_filter:
                phase_detail.append(
                    PhaseTimelineEntry(
                        phase=_json_str(p.get("phase", "")),
                        model=_json_str_optional(p.get("model")),
                        duration_ms=_json_int(p.get("duration_ms", 0), 0),
                        cost_usd=_json_float_optional(p.get("cost_usd")),
                        success=_json_bool(p.get("success", True), True),
                        session_id=_json_str(p.get("session_id", "")),
                        error=_json_str_optional(p.get("error")),
                    )
                )

    return ShowResult(
        header=header,
        timeline=timeline,
        review_summary=review_summary,
        has_decision=has_decision,
        decision_success=decision_success,
        has_ci_fix=has_ci_fix,
        ci_fix_attempts=len(ci_fix_phases),
        ci_fix_final_success=ci_fix_final_success,
        phase_filter=phase_filter,
        phase_detail=phase_detail,
    )


# ---------------------------------------------------------------------------
# Rendering layer: rich output
# ---------------------------------------------------------------------------

_STATUS_STYLES = {
    "completed": ("green", "COMPLETED"),
    "failed": ("red", "FAILED"),
    "running": ("yellow", "RUNNING"),
}


def render_run_header(console: Console, header: RunHeader) -> None:
    """FR-2: Render run header as a Rich Panel."""
    style, label = _STATUS_STYLES.get(header.status, ("dim", header.status.upper()))

    lines = [
        f"Run ID:   {header.run_id}",
        f"Status:   [{style}]{label}[/{style}]",
    ]
    if header.branch_name:
        lines.append(f"Branch:   {header.branch_name}")
    lines.append(f"Cost:     ${header.total_cost_usd:.4f}")
    lines.append(f"Duration: {_format_duration_ms(header.wall_clock_ms)}")
    if header.started_at:
        lines.append(f"Started:  {header.started_at}")
    if header.finished_at:
        lines.append(f"Finished: {header.finished_at}")
    if header.prompt_truncated:
        lines.append(f"Prompt:   {header.prompt_truncated}")
    if header.source_issue_url:
        lines.append(f"Issue:    {header.source_issue_url}")
    if header.last_successful_phase:
        lines.append(f"Resumed:  from {header.last_successful_phase}")

    console.print(Panel("\n".join(lines), title="Run Details", border_style=style))


def render_phase_timeline(
    console: Console, entries: list[PhaseTimelineEntry]
) -> None:
    """FR-3: Render phase timeline as a Rich Table."""
    if not entries:
        return

    table = Table(title="Phase Timeline")
    table.add_column("Phase", style="cyan")
    table.add_column("Model", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Status", justify="center")

    for entry in entries:
        phase_label = entry.phase
        if entry.round_number is not None:
            phase_label = f"{entry.phase} (round {entry.round_number})"

        model_str = entry.model or ""
        cost_str = f"${entry.cost_usd:.4f}" if entry.cost_usd is not None else "-"
        status_str = "[green]\u2713[/green]" if entry.success else "[red]\u2717[/red]"

        style = "dim" if entry.is_skipped else None
        table.add_row(
            phase_label,
            model_str,
            _format_duration_ms(entry.duration_ms),
            cost_str,
            status_str,
            style=style,
        )

    console.print(table)


def render_review_summary(console: Console, summary: ReviewSummary) -> None:
    """FR-4: Render review summary as a Rich Panel."""
    lines = [
        f"Review Rounds:     {summary.review_rounds}",
        f"Fix Iterations:    {summary.fix_iterations}",
    ]
    for i, count in enumerate(summary.per_round_review_counts, 1):
        lines.append(f"  Round {i}:         {count} review(s)")

    console.print(
        Panel("\n".join(lines), title="Review Summary", border_style="blue")
    )


def render_artifact_links(console: Console, header: RunHeader) -> None:
    """FR-7: Render artifact file paths."""
    lines: list[str] = []
    if header.prd_rel:
        lines.append(f"PRD:    {header.prd_rel}")
    if header.task_rel:
        lines.append(f"Tasks:  {header.task_rel}")
    if header.branch_name:
        lines.append(f"Branch: {header.branch_name}")
    if header.source_issue_url:
        lines.append(f"Issue:  {header.source_issue_url}")

    if lines:
        console.print(
            Panel("\n".join(lines), title="Artifacts", border_style="dim")
        )


def render_phase_detail(
    console: Console,
    entries: list[PhaseTimelineEntry],
    phase_name: str,
) -> None:
    """FR-9: Render extended detail for a filtered phase."""
    if not entries:
        console.print(f"No executions of phase '{phase_name}' in this run.")
        return

    table = Table(title=f"Phase Detail: {phase_name}")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Model", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Session ID", style="dim")
    table.add_column("Error", style="red")

    for idx, entry in enumerate(entries, 1):
        cost_str = f"${entry.cost_usd:.4f}" if entry.cost_usd is not None else "-"
        status_str = "[green]\u2713[/green]" if entry.success else "[red]\u2717[/red]"
        error_str = (entry.error or "")[:80] if entry.error else ""

        table.add_row(
            str(idx),
            entry.model or "",
            _format_duration_ms(entry.duration_ms),
            cost_str,
            status_str,
            entry.session_id or "",
            error_str,
        )

    console.print(table)


def render_show(console: Console, result: ShowResult) -> None:
    """Orchestrate rendering of all sections."""
    render_run_header(console, result.header)
    console.print()

    if result.phase_filter and result.phase_detail:
        render_phase_detail(console, result.phase_detail, result.phase_filter)
        return

    render_phase_timeline(console, result.timeline)

    if result.review_summary:
        console.print()
        render_review_summary(console, result.review_summary)

    if result.has_decision:
        console.print()
        status = "[green]PASSED[/green]" if result.decision_success else "[red]FAILED[/red]"
        console.print(
            Panel(f"Decision Gate: {status}", title="Decision", border_style="dim")
        )

    if result.has_ci_fix:
        console.print()
        ci_status = (
            "[green]PASSED[/green]"
            if result.ci_fix_final_success
            else "[red]FAILED[/red]"
        )
        console.print(
            Panel(
                f"CI Fix Attempts: {result.ci_fix_attempts}\nFinal Status:    {ci_status}",
                title="CI Fix",
                border_style="dim",
            )
        )

    console.print()
    render_artifact_links(console, result.header)
