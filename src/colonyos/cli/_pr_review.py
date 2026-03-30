"""PR review command: monitor and auto-fix PR review comments."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import ColonyConfig, load_config
from colonyos.models import RunStatus

logger = logging.getLogger(__name__)


def _find_branch_artifacts(
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
) -> tuple[str, str]:
    """Find PRD and task files associated with a branch.

    Returns (prd_rel, task_rel) paths relative to repo root.
    Falls back to empty strings if not found.
    """
    prd_dir = repo_root / config.prds_dir
    task_dir = repo_root / config.tasks_dir

    # Try to find files that match the branch slug
    branch_slug = branch_name.replace(config.branch_prefix, "").replace("/", "_")

    prd_rel = ""
    task_rel = ""

    if prd_dir.exists():
        for prd_file in prd_dir.glob("*prd*.md"):
            if branch_slug in prd_file.name or branch_name in prd_file.name:
                prd_rel = str(prd_file.relative_to(repo_root))
                break

    if task_dir.exists():
        for task_file in task_dir.glob("*tasks*.md"):
            if branch_slug in task_file.name or branch_name in task_file.name:
                task_rel = str(task_file.relative_to(repo_root))
                break

    return prd_rel, task_rel


def _get_latest_commit_sha(repo_root: Path) -> str:
    """Get the SHA of the latest commit."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


@app.command("pr-review")
@click.argument("pr_number", type=int)
@click.option("--watch", is_flag=True, help="Continuously poll for new review comments.")
@click.option("--poll-interval", default=None, type=int, help="Poll interval in seconds (default: 60).")
@click.option("--max-cost", default=None, type=float, help="Override per-PR budget cap (default: $5).")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
def pr_review(
    pr_number: int,
    watch: bool,
    poll_interval: int | None,
    max_cost: float | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Monitor and auto-fix PR review comments.

    PR_NUMBER is the pull request number to monitor.

    Fetches inline review comments, triages them for actionability,
    and runs the fix pipeline for actionable feedback. Posts replies
    to comment threads with fix commit links.

    Use --watch for continuous monitoring of new comments.
    """
    from colonyos.pr_review import (
        PRReviewState,
        build_commit_url,
        check_budget_cap,
        check_circuit_breaker,
        check_fix_rounds,
        fetch_pr_review_comments,
        fetch_pr_state,
        format_fix_reply,
        format_summary_message,
        load_pr_review_state,
        post_pr_review_reply,
        post_pr_summary_comment,
        save_pr_review_state,
        triage_pr_review_comment,
    )
    from colonyos.orchestrator import run_thread_fix

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Resolve poll interval and budget
    effective_poll_interval = poll_interval or config.pr_review.poll_interval_seconds
    effective_budget = max_cost or config.pr_review.budget_per_pr

    # Check PR state (FR-14: skip merged/closed PRs)
    try:
        pr_state = fetch_pr_state(pr_number, repo_root)
    except Exception as exc:
        click.echo(f"Error fetching PR #{pr_number}: {exc}", err=True)
        sys.exit(1)

    if pr_state.state in ("merged", "closed"):
        click.echo(f"PR #{pr_number} is {pr_state.state}. Nothing to do.")
        return

    click.echo(f"[colonyos] Monitoring PR #{pr_number} on branch {pr_state.head_ref}")
    click.echo(f"[colonyos] Budget: ${effective_budget:.2f}, Poll interval: {effective_poll_interval}s")

    # Load or create state
    loaded_state = load_pr_review_state(repo_root, pr_number)
    state: PRReviewState
    if loaded_state is None:
        state = PRReviewState(pr_number=pr_number)
        save_pr_review_state(repo_root, state)
    else:
        state = loaded_state

    def process_comments() -> list[tuple[str, str]]:
        """Process new actionable comments. Returns list of (sha, summary) for fixes."""
        nonlocal state, pr_state
        fixes_applied: list[tuple[str, str]] = []

        # Safety checks
        if not check_budget_cap(state, effective_budget):
            click.echo(
                f"[colonyos] Budget cap reached (${state.cumulative_cost_usd:.2f} spent). "
                "Pausing auto-fixes."
            )
            post_pr_summary_comment(
                pr_number,
                f"Max budget reached (${state.cumulative_cost_usd:.2f} spent), pausing auto-fixes.",
                repo_root,
            )
            return fixes_applied

        if not check_circuit_breaker(state, config.pr_review.circuit_breaker_threshold):
            # Set pause state for circuit breaker cooldown
            if not state.queue_paused:
                state.queue_paused = True
                state.queue_paused_at = datetime.now(timezone.utc).isoformat()
                save_pr_review_state(repo_root, state)
            cooldown = config.pr_review.circuit_breaker_cooldown_minutes
            click.echo(
                f"[colonyos] Circuit breaker triggered ({state.consecutive_failures} failures). "
                f"Will auto-recover after {cooldown} minutes."
            )
            return fixes_applied

        if not check_fix_rounds(state, config.pr_review.max_fix_rounds_per_pr):
            click.echo(
                f"[colonyos] Max fix rounds reached ({state.fix_rounds}). Stopping."
            )
            return fixes_applied

        # Fetch comments
        try:
            comments = fetch_pr_review_comments(pr_number, repo_root)
        except Exception as exc:
            click.echo(f"[colonyos] Error fetching comments: {exc}", err=True)
            state.consecutive_failures += 1
            save_pr_review_state(repo_root, state)
            return fixes_applied

        # Filter to new comments only (FR-8: only comments after watch_started_at)
        # Also exclude already-processed comments for deduplication across restarts
        # Use datetime parsing for robust ISO timestamp comparison
        watch_started_dt = datetime.fromisoformat(state.watch_started_at)
        new_comments = [
            c for c in comments
            if not state.is_processed(c.id)
            and datetime.fromisoformat(c.created_at) >= watch_started_dt
        ]

        if not new_comments:
            if not quiet:
                click.echo(f"[colonyos] No new actionable comments found.")
            return fixes_applied

        click.echo(f"[colonyos] Found {len(new_comments)} new comment(s) to process.")

        for comment in new_comments:
            if not check_budget_cap(state, effective_budget):
                click.echo("[colonyos] Budget cap reached during processing. Stopping.")
                break

            # Triage the comment
            if not quiet:
                click.echo(f"[colonyos] Triaging comment {comment.id} from @{comment.reviewer}...")

            try:
                triage_result = triage_pr_review_comment(
                    comment.body,
                    file_path=comment.path,
                    line_number=comment.line,
                    repo_root=repo_root,
                    project_name=config.project.name if config.project else "",
                    project_description=config.project.description if config.project else "",
                    project_stack=config.project.stack if config.project else "",
                    vision=config.vision,
                )
            except Exception as exc:
                click.echo(f"[colonyos] Triage error: {exc}", err=True)
                state.mark_processed(comment.id, "triage-error")
                save_pr_review_state(repo_root, state)
                continue

            if not triage_result.actionable:
                if not quiet:
                    click.echo(
                        f"[colonyos] Comment {comment.id} not actionable: {triage_result.reasoning[:100]}"
                    )
                state.mark_processed(comment.id, "not-actionable")
                save_pr_review_state(repo_root, state)
                continue

            click.echo(
                f"[colonyos] Comment {comment.id} is actionable ({triage_result.confidence:.0%}): "
                f"{triage_result.summary}"
            )

            # Find PRD and task files for the branch
            prd_rel, task_rel = _find_branch_artifacts(repo_root, config, pr_state.head_ref)

            # Run the fix pipeline (FR-15: use source_type for analytics)
            # Security: Sanitize untrusted comment body before passing to fix agent
            from colonyos.sanitize import sanitize_untrusted_content
            sanitized_comment_body = sanitize_untrusted_content(comment.body)

            try:
                run_log = run_thread_fix(
                    fix_prompt=sanitized_comment_body,
                    branch_name=pr_state.head_ref,
                    pr_url=pr_state.url,
                    original_prompt=triage_result.summary,
                    prd_rel=prd_rel,
                    task_rel=task_rel,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    quiet=quiet,
                    expected_head_sha=pr_state.head_sha,
                    source_type="pr_review_fix",
                    review_comment_id=comment.id,
                    # PR review context for template selection and rich prompts
                    pr_review_context={
                        "file_path": comment.path,
                        "line_number": comment.line,
                        "reviewer_username": comment.reviewer,
                        "comment_url": comment.html_url,
                        "review_comment": sanitized_comment_body,
                    },
                )

                # Update state
                state.cumulative_cost_usd += run_log.total_cost_usd
                state.fix_rounds += 1

                if run_log.status == RunStatus.COMPLETED:
                    # Get the commit SHA from the most recent commit
                    commit_sha = _get_latest_commit_sha(repo_root)
                    commit_url = build_commit_url(pr_state.url, commit_sha)

                    # Post reply to comment thread (FR-5)
                    reply_msg = format_fix_reply(
                        commit_sha, commit_url, triage_result.summary
                    )
                    post_pr_review_reply(pr_number, comment.id, reply_msg, repo_root)

                    fixes_applied.append((commit_sha, triage_result.summary))
                    state.consecutive_failures = 0
                    state.mark_processed(comment.id, run_log.run_id)
                    click.echo(f"[colonyos] Fix applied: {commit_sha[:7]}")

                    # Update expected HEAD SHA for subsequent fixes in this cycle
                    # This prevents SHA mismatch errors when processing multiple comments
                    from colonyos.pr_review import PRState
                    pr_state = PRState(
                        state=pr_state.state,
                        head_sha=commit_sha,
                        head_ref=pr_state.head_ref,
                        url=pr_state.url,
                    )
                else:
                    state.consecutive_failures += 1
                    state.mark_processed(comment.id, f"failed-{run_log.run_id}")
                    click.echo(f"[colonyos] Fix failed for comment {comment.id}")

            except Exception as exc:
                click.echo(f"[colonyos] Fix error: {exc}", err=True)
                state.consecutive_failures += 1
                state.mark_processed(comment.id, "fix-error")

            save_pr_review_state(repo_root, state)

        return fixes_applied

    # Single run or watch mode
    if watch:
        click.echo("[colonyos] Watch mode enabled. Press Ctrl+C to stop.")
        try:
            while True:
                # Re-check PR state each cycle
                try:
                    pr_state = fetch_pr_state(pr_number, repo_root)
                    if pr_state.state in ("merged", "closed"):
                        click.echo(f"[colonyos] PR #{pr_number} is now {pr_state.state}. Exiting watch mode.")
                        break
                except Exception as exc:
                    # Log the error but continue watching - transient network issues
                    # shouldn't stop the watch loop. Log for debugging.
                    logger.warning(
                        "Failed to check PR #%d state during watch: %s",
                        pr_number, exc,
                    )
                    # Continue watching

                # Skip processing if circuit breaker is open (still cooling down)
                if state.queue_paused:
                    # Check if cooldown has expired for auto-recovery
                    if state.queue_paused_at:
                        try:
                            paused_at = datetime.fromisoformat(state.queue_paused_at)
                            cooldown_sec = config.pr_review.circuit_breaker_cooldown_minutes * 60
                            elapsed = (datetime.now(timezone.utc) - paused_at).total_seconds()
                            if elapsed >= cooldown_sec:
                                # Auto-recover
                                state.queue_paused = False
                                state.queue_paused_at = None
                                state.consecutive_failures = 0
                                save_pr_review_state(repo_root, state)
                                click.echo("[colonyos] Circuit breaker auto-recovered after cooldown.")
                            else:
                                remaining = (cooldown_sec - elapsed) / 60
                                if not quiet:
                                    click.echo(f"[colonyos] Circuit breaker paused. {remaining:.0f} minutes remaining.")
                                time.sleep(effective_poll_interval)
                                continue
                        except (ValueError, TypeError):
                            # Malformed timestamp; remain paused
                            time.sleep(effective_poll_interval)
                            continue

                fixes = process_comments()

                # Post summary if fixes were applied (FR-6)
                if fixes:
                    summary_msg = format_summary_message(fixes)
                    post_pr_summary_comment(pr_number, summary_msg, repo_root)

                # Check safety guards before sleeping
                if not check_budget_cap(state, effective_budget):
                    click.echo("[colonyos] Budget exhausted. Exiting watch mode.")
                    break

                # Circuit breaker with cooldown/recovery (FR-13)
                if not check_circuit_breaker(state, config.pr_review.circuit_breaker_threshold):
                    if not state.queue_paused:
                        # First trigger: set pause timestamp
                        state.queue_paused = True
                        state.queue_paused_at = datetime.now(timezone.utc).isoformat()
                        save_pr_review_state(repo_root, state)
                        cooldown = config.pr_review.circuit_breaker_cooldown_minutes
                        click.echo(
                            f"[colonyos] Circuit breaker triggered ({state.consecutive_failures} "
                            f"consecutive failures). Will auto-recover after {cooldown} minutes."
                        )
                    else:
                        # Check if cooldown has expired for auto-recovery
                        if state.queue_paused_at:
                            try:
                                paused_at = datetime.fromisoformat(state.queue_paused_at)
                                cooldown_sec = config.pr_review.circuit_breaker_cooldown_minutes * 60
                                elapsed = (datetime.now(timezone.utc) - paused_at).total_seconds()
                                if elapsed >= cooldown_sec:
                                    # Auto-recover
                                    state.queue_paused = False
                                    state.queue_paused_at = None
                                    state.consecutive_failures = 0
                                    save_pr_review_state(repo_root, state)
                                    click.echo("[colonyos] Circuit breaker auto-recovered after cooldown.")
                            except (ValueError, TypeError):
                                pass  # Malformed timestamp; remain paused
                    # Sleep during pause, then loop to re-check
                    time.sleep(effective_poll_interval)
                    continue

                time.sleep(effective_poll_interval)

        except KeyboardInterrupt:
            click.echo("\n[colonyos] Watch mode stopped.")
    else:
        # Single run
        fixes = process_comments()
        if fixes:
            summary_msg = format_summary_message(fixes)
            post_pr_summary_comment(pr_number, summary_msg, repo_root)
            click.echo(f"[colonyos] Applied {len(fixes)} fix(es).")
        else:
            click.echo("[colonyos] No fixes applied.")

    # Final state save
    save_pr_review_state(repo_root, state)
    click.echo(f"[colonyos] Total cost: ${state.cumulative_cost_usd:.2f}")
