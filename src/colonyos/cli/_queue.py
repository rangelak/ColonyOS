"""``colonyos queue`` command group — batch feature execution queue.

Contains queue state persistence helpers, verdict/PR extraction utilities,
and the ``queue`` Click group with its ``add``, ``start``, ``status``,
``clear``, and ``unpause`` subcommands.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from colonyos.config import load_config, runs_dir_path
from colonyos.models import (
    QueueItem,
    QueueItemStatus,
    QueueState,
    QueueStatus,
    RunLog,
    RunStatus,
)
from colonyos.naming import generate_timestamp

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root


# ---------------------------------------------------------------------------
# Queue state helpers
# ---------------------------------------------------------------------------

QUEUE_FILE = "queue.json"


def _save_queue_state(repo_root: Path, state: QueueState) -> Path:
    """Persist queue state atomically to .colonyos/queue.json.

    Writes to a temporary file then renames to avoid truncated files on crash.
    """
    colonyos_dir = repo_root / ".colonyos"
    colonyos_dir.mkdir(parents=True, exist_ok=True)
    path = colonyos_dir / QUEUE_FILE
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(colonyos_dir), suffix=".tmp", prefix="queue_",
    )
    fd_closed = False
    try:
        os.write(fd, json.dumps(state.to_dict(), indent=2).encode("utf-8"))
        os.close(fd)
        fd_closed = True
        os.replace(tmp_path_str, str(path))
    except BaseException:
        if not fd_closed:
            try:
                os.close(fd)
            except OSError:
                pass
        Path(tmp_path_str).unlink(missing_ok=True)
        raise
    return path


def _load_queue_state(repo_root: Path) -> QueueState | None:
    """Load queue state from .colonyos/queue.json, or None if absent."""
    path = repo_root / ".colonyos" / QUEUE_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return QueueState.from_dict(data)


def _compute_queue_elapsed_hours(state: QueueState) -> float:
    """Compute elapsed hours from the queue's start_time_iso."""
    if not state.start_time_iso:
        return 0.0
    original_start = datetime.fromisoformat(state.start_time_iso)
    now = datetime.now(timezone.utc)
    return (now - original_start).total_seconds() / 3600.0


_NOGO_VERDICT_RE = re.compile(r"VERDICT:\s*NO-GO", re.IGNORECASE)


def _is_nogo_verdict(log: RunLog) -> bool:
    """Check if a run log has a NO-GO decision verdict.

    Uses the same ``VERDICT: NO-GO`` regex pattern as the orchestrator's
    ``_extract_verdict()`` to stay in sync with the decision phase output
    contract.
    """
    for phase in log.phases:
        if phase.phase.value == "decision":
            verdict_text = phase.artifacts.get("result", "")
            if _NOGO_VERDICT_RE.search(verdict_text):
                return True
    return False


def _extract_pr_url_from_log(log: RunLog) -> str | None:
    """Extract PR URL from the deliver phase artifacts."""
    for phase in log.phases:
        if phase.phase.value == "deliver":
            pr_url = phase.artifacts.get("pr_url", "")
            if pr_url:
                return pr_url
    return None


# ---------------------------------------------------------------------------
# Queue group and subcommands
# ---------------------------------------------------------------------------


@app.group()
def queue():
    """Manage the feature execution queue."""
    pass


@queue.command()
@click.argument("prompts", nargs=-1)
@click.option("--issue", "issue_refs", multiple=True, help="GitHub issue number or URL to enqueue.")
def add(prompts: tuple[str, ...], issue_refs: tuple[str, ...]) -> None:
    """Add items (prompts and/or issue refs) to the execution queue."""
    if not prompts and not issue_refs:
        click.echo("Error: provide at least one prompt or --issue.", err=True)
        raise SystemExit(1)

    repo_root = _find_repo_root()

    state = _load_queue_state(repo_root)
    if state is None:
        state = QueueState(
            queue_id=f"queue-{generate_timestamp()}",
        )

    new_items: list[QueueItem] = []

    # Add free-text prompts
    for prompt_text in prompts:
        item = QueueItem(
            id=str(uuid.uuid4()),
            source_type="prompt",
            source_value=prompt_text,
            status=QueueItemStatus.PENDING,
        )
        new_items.append(item)

    # Add issue references (validate at add-time)
    for ref in issue_refs:
        from colonyos.github import fetch_issue, parse_issue_ref

        number = parse_issue_ref(ref)
        issue = fetch_issue(number, repo_root)

        item = QueueItem(
            id=str(uuid.uuid4()),
            source_type="issue",
            source_value=str(issue.number),
            status=QueueItemStatus.PENDING,
            issue_title=issue.title,
        )
        new_items.append(item)

    state.items.extend(new_items)
    _save_queue_state(repo_root, state)

    pending_count = sum(1 for i in state.items if i.status == QueueItemStatus.PENDING)
    click.echo(f"Added {len(new_items)} item(s) to queue. Total pending: {pending_count}")


@queue.command("start")
@click.option("--max-cost", type=float, default=None, help="Maximum aggregate USD spend for the queue.")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the queue.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
def queue_start(
    max_cost: float | None,
    max_hours: float | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Process pending queue items sequentially through the pipeline."""
    from colonyos.orchestrator import run as run_orchestrator

    from colonyos.cli._display import (
        _format_queue_item_source,
        _print_queue_summary,
    )

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo("No ColonyOS config found. Run `colonyos init` first.", err=True)
        sys.exit(1)

    state = _load_queue_state(repo_root)
    if state is None:
        click.echo("No queue found. Run `colonyos queue add` first.", err=True)
        sys.exit(1)

    # Recover any items left in RUNNING state from a prior crash/interrupt.
    # A RUNNING item in persisted state always means the prior run was killed.
    recovered = 0
    for item in state.items:
        if item.status == QueueItemStatus.RUNNING:
            item.status = QueueItemStatus.PENDING
            recovered += 1
    if recovered:
        _save_queue_state(repo_root, state)
        click.echo(f"Recovered {recovered} interrupted item(s) back to pending.")

    pending_items = [i for i in state.items if i.status == QueueItemStatus.PENDING]
    if not pending_items:
        click.echo("No pending items in queue.")
        _print_queue_summary(state)
        return

    # Resolve caps
    effective_max_cost = max_cost if max_cost is not None else config.budget.max_total_usd
    effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours

    # Set start time if not already set (resume case)
    if not state.start_time_iso:
        state.start_time_iso = datetime.now(timezone.utc).isoformat()
    state.status = QueueStatus.RUNNING
    _save_queue_state(repo_root, state)

    click.echo(f"Starting queue {state.queue_id}: {len(pending_items)} pending item(s)")

    # Track the item currently being processed so we can revert it on interrupt.
    current_item: QueueItem | None = None

    try:
        for item in state.items:
            if item.status != QueueItemStatus.PENDING:
                continue

            # --- Time cap check ---
            elapsed = _compute_queue_elapsed_hours(state)
            if elapsed >= effective_max_hours:
                click.echo(
                    f"\nTime limit reached ({elapsed:.1f}h / {effective_max_hours:.1f}h). "
                    f"Halting queue."
                )
                state.status = QueueStatus.INTERRUPTED
                _save_queue_state(repo_root, state)
                break

            # --- Budget cap check ---
            if state.aggregate_cost_usd >= effective_max_cost:
                click.echo(
                    f"\nBudget limit reached (${state.aggregate_cost_usd:.2f} / "
                    f"${effective_max_cost:.2f}). Halting queue."
                )
                state.status = QueueStatus.INTERRUPTED
                _save_queue_state(repo_root, state)
                break

            # Mark item as running
            item.status = QueueItemStatus.RUNNING
            current_item = item
            _save_queue_state(repo_root, state)

            source_display = _format_queue_item_source(item)
            click.echo(f"\n--- Processing: {source_display} ---")

            start_ms = int(time.time() * 1000)

            try:
                # Resolve prompt
                if item.source_type == "issue":
                    from colonyos.github import fetch_issue, format_issue_as_prompt

                    issue = fetch_issue(int(item.source_value), repo_root)
                    prompt_text = format_issue_as_prompt(issue)
                    source_issue = issue.number
                    source_issue_url = issue.url
                else:
                    prompt_text = item.source_value
                    source_issue = None
                    source_issue_url = None

                log = run_orchestrator(
                    prompt_text,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    quiet=quiet,
                    source_issue=source_issue,
                    source_issue_url=source_issue_url,
                )

                end_ms = int(time.time() * 1000)
                item.run_id = log.run_id
                item.cost_usd = log.total_cost_usd
                item.duration_ms = end_ms - start_ms

                # Determine outcome
                if log.status == RunStatus.FAILED and _is_nogo_verdict(log):
                    item.status = QueueItemStatus.REJECTED
                    click.echo("  Item rejected (NO-GO verdict).")
                elif log.status == RunStatus.FAILED:
                    item.status = QueueItemStatus.FAILED
                    item.error = "Pipeline failed"
                    click.echo("  Item failed.")
                else:
                    item.status = QueueItemStatus.COMPLETED
                    item.pr_url = _extract_pr_url_from_log(log)
                    click.echo(f"  Item completed. PR: {item.pr_url or 'N/A'}")

            except Exception as exc:
                end_ms = int(time.time() * 1000)
                item.status = QueueItemStatus.FAILED
                # Truncate error to avoid persisting sensitive info from tracebacks.
                item.error = str(exc)[:500]
                item.duration_ms = end_ms - start_ms
                click.echo(f"  Item failed: {exc}", err=True)

            current_item = None
            state.aggregate_cost_usd += item.cost_usd
            _save_queue_state(repo_root, state)

            # --- Post-item budget cap check ---
            if state.aggregate_cost_usd >= effective_max_cost:
                click.echo(
                    f"\nBudget limit reached (${state.aggregate_cost_usd:.2f} / "
                    f"${effective_max_cost:.2f}). Halting queue."
                )
                state.status = QueueStatus.INTERRUPTED
                _save_queue_state(repo_root, state)
                break

    except KeyboardInterrupt:
        click.echo("\nQueue interrupted by user.")
        # Revert the in-progress item back to PENDING so it can be retried.
        if current_item is not None and current_item.status == QueueItemStatus.RUNNING:
            current_item.status = QueueItemStatus.PENDING
        state.status = QueueStatus.INTERRUPTED
        _save_queue_state(repo_root, state)
        _print_queue_summary(state)
        return

    # Mark completed if all items processed
    all_done = all(
        i.status in (QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.REJECTED)
        for i in state.items
    )
    if all_done and state.status == QueueStatus.RUNNING:
        state.status = QueueStatus.COMPLETED
    _save_queue_state(repo_root, state)

    _print_queue_summary(state)


@queue.command("status")
def queue_status() -> None:
    """Show the current state of the execution queue."""
    from colonyos.cli._display import _print_queue_summary

    repo_root = _find_repo_root()
    state = _load_queue_state(repo_root)

    if state is None or not state.items:
        click.echo("No queue found or queue is empty.")
        return

    _print_queue_summary(state)


@queue.command()
def clear() -> None:
    """Remove all pending items from the queue."""
    repo_root = _find_repo_root()
    state = _load_queue_state(repo_root)

    if state is None:
        click.echo("No queue found. Nothing to clear.")
        return

    before = len(state.items)
    state.items = [i for i in state.items if i.status != QueueItemStatus.PENDING]
    removed = before - len(state.items)

    _save_queue_state(repo_root, state)
    click.echo(f"Cleared {removed} pending item(s). {len(state.items)} item(s) remaining.")


@queue.command()
def unpause() -> None:
    """Unpause the queue after a circuit breaker trip.

    Resets the circuit breaker state so the queue executor resumes
    processing items.
    """
    from colonyos.config import runs_dir_path
    from colonyos.slack import load_watch_state, save_watch_state

    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)
    if not runs_dir.exists():
        click.echo("No watch state found.")
        return

    # Find the most recent watch state file
    watch_files = sorted(runs_dir.glob("watch_state_*.json"), reverse=True)
    if not watch_files:
        click.echo("No watch state found.")
        return

    import json

    for wf in watch_files:
        data = json.loads(wf.read_text(encoding="utf-8"))
        watch_id = data.get("watch_id", "")
        state = load_watch_state(repo_root, watch_id)
        if state and state.queue_paused:
            state.queue_paused = False
            state.queue_paused_at = None
            state.consecutive_failures = 0
            save_watch_state(repo_root, state)
            click.echo(f"Queue unpaused for watch session '{watch_id}'.")
            return

    click.echo("Queue is not currently paused.")
