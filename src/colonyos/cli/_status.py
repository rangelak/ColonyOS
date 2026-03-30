"""Status command: show recent runs, loop summaries, and queue state."""

from __future__ import annotations

import json
import time

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import load_config, runs_dir_path
from colonyos.models import QueueItemStatus


@app.command()
@click.option("-n", "--limit", default=10, help="Number of recent runs to show.")
def status(limit: int) -> None:
    """Show recent ColonyOS runs and loop summaries."""
    from colonyos.cli._legacy import _load_queue_state

    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)

    if not runs_dir.exists():
        click.echo("No runs yet. Run `colonyos run \"<feature>\"` to start.")
        return

    # --- Loop state summaries ---
    loop_files = sorted(runs_dir.glob("loop_state_*.json"), reverse=True)
    if loop_files:
        click.echo("=== Loop Summaries ===\n")
        for lf in loop_files[:3]:
            try:
                data = json.loads(lf.read_text(encoding="utf-8"))
                lid = data.get("loop_id", "?")
                cur = data.get("current_iteration", 0)
                total = data.get("total_iterations", 0)
                cost = data.get("aggregate_cost_usd", 0)
                st = data.get("status", "unknown")
                click.echo(
                    f"  Loop {lid}: {cur}/{total} iterations, "
                    f"${cost:.4f} spent, status: {st}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {lf.name}: (corrupted)")

        # Heartbeat staleness check
        heartbeat = runs_dir / "heartbeat"
        if heartbeat.exists():
            age_seconds = time.time() - heartbeat.stat().st_mtime
            if age_seconds > 300:  # 5 minutes
                click.echo(
                    f"\n  \u26a0 Warning: Heartbeat file is stale "
                    f"({age_seconds / 60:.0f} minutes old). "
                    f"A running loop may be stuck."
                )

        click.echo()

    # --- Individual run logs ---
    log_files = sorted(
        [f for f in runs_dir.glob("*.json") if not f.name.startswith("loop_state_")],
        reverse=True,
    )[:limit]

    if not log_files and not loop_files:
        click.echo("No runs found.")

    if log_files:
        click.echo("=== Recent Runs ===\n")
        for log_file in log_files:
            try:
                data = json.loads(log_file.read_text(encoding="utf-8"))
                status_val = data.get("status", "unknown")
                cost = data.get("total_cost_usd", 0)
                prompt_preview = (data.get("prompt", "")[:60] + "...") if len(data.get("prompt", "")) > 60 else data.get("prompt", "")

                # Check if this failed run is resumable
                resumable_tag = ""
                if (
                    status_val == "failed"
                    and data.get("branch_name")
                    and data.get("prd_rel")
                    and data.get("task_rel")
                    and any(p.get("success") for p in data.get("phases", []))
                ):
                    resumable_tag = " [resumable]"

                issue_tag = ""
                si = data.get("source_issue")
                si_url = data.get("source_issue_url")
                if si:
                    issue_tag = f"#{si} {si_url or ''} "

                click.echo(
                    f"  {data.get('run_id', '?'):40s} "
                    f"{status_val:10s}{resumable_tag} "
                    f"${cost:>7.4f}  "
                    f"{issue_tag}"
                    f"{prompt_preview}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {log_file.name}: (corrupted)")

    # --- Slack watch state summaries ---
    watch_files = sorted(runs_dir.glob("watch_state_*.json"), reverse=True)
    if watch_files:
        click.echo("=== Slack Watch Sessions ===\n")
        for wf in watch_files[:3]:
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
                wid = data.get("watch_id", "?")
                runs_count = data.get("runs_triggered", 0)
                cost = data.get("aggregate_cost_usd", 0)
                click.echo(
                    f"  Watch {wid}: {runs_count} runs triggered, "
                    f"${cost:.4f} spent"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {wf.name}: (corrupted)")
        click.echo()

    # --- PR Review state summaries (FR-17) ---
    pr_review_files = sorted(runs_dir.glob("pr_review_state_*.json"), reverse=True)
    if pr_review_files:
        click.echo("=== PR Review Sessions ===\n")
        for prf in pr_review_files[:5]:
            try:
                data = json.loads(prf.read_text(encoding="utf-8"))
                pr_num = data.get("pr_number", "?")
                fix_rounds = data.get("fix_rounds", 0)
                cost = data.get("cumulative_cost_usd", 0)
                processed = len(data.get("processed_comment_ids", {}))
                paused = data.get("queue_paused", False)
                status_tag = " [paused]" if paused else ""
                click.echo(
                    f"  PR #{pr_num}: {fix_rounds} fixes applied, "
                    f"{processed} comments processed, "
                    f"${cost:.4f} spent{status_tag}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {prf.name}: (corrupted)")
        click.echo()

    # --- Learnings ledger ---
    from colonyos.learnings import count_learnings, learnings_path as _learnings_path

    lpath = _learnings_path(repo_root)
    if lpath.exists():
        count = count_learnings(repo_root)
        click.echo(f"\nLearnings ledger: {count} entries")
    else:
        click.echo("\nLearnings ledger: not found")

    # --- Queue summary ---
    queue_state = _load_queue_state(repo_root)
    if queue_state and queue_state.items:
        total = len(queue_state.items)
        completed = sum(1 for i in queue_state.items if i.status == QueueItemStatus.COMPLETED)
        failed = sum(1 for i in queue_state.items if i.status == QueueItemStatus.FAILED)
        rejected = sum(1 for i in queue_state.items if i.status == QueueItemStatus.REJECTED)
        running = sum(1 for i in queue_state.items if i.status == QueueItemStatus.RUNNING)
        cost = queue_state.aggregate_cost_usd

        parts = [f"Queue: {completed}/{total} completed"]
        if running:
            parts.append(f"{running} running")
        if failed:
            parts.append(f"{failed} failed")
        if rejected:
            parts.append(f"{rejected} rejected")
        parts.append(f"${cost:.2f} spent")
        click.echo("\n" + ", ".join(parts))
