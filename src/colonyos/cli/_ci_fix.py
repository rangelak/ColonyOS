"""CI fix command: auto-fix CI failures on a pull request."""

from __future__ import annotations

import subprocess
import sys

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import load_config
from colonyos.models import RunLog, RunStatus
from colonyos.naming import generate_timestamp


@app.command("ci-fix")
@click.argument("pr_ref")
@click.option("--max-retries", default=1, type=int, help="Max fix-push-wait cycles.")
@click.option("--wait/--no-wait", default=False, help="Wait for CI after pushing fix.")
@click.option("--wait-timeout", default=600, type=int, help="Seconds to wait for CI per cycle.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
def ci_fix(
    pr_ref: str,
    max_retries: int,
    wait: bool,
    wait_timeout: int,
    verbose: bool,
) -> None:
    """Fix CI failures on a pull request.

    PR_REF is a pull request number (e.g. 42) or full GitHub PR URL.
    Fetches failed check logs, runs an AI agent to fix the code, and
    pushes a fix commit.
    """
    from colonyos.ci import (
        all_checks_pass,
        check_pr_author_mismatch,
        collect_ci_failure_context,
        fetch_pr_checks,
        format_ci_failures_as_prompt,
        parse_pr_ref,
        poll_pr_checks,
        validate_branch_not_behind,
        validate_clean_worktree,
        validate_gh_auth,
    )
    from colonyos.orchestrator import _build_ci_fix_prompt, _save_run_log

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    # Parse PR reference
    try:
        pr_number = parse_pr_ref(pr_ref)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # Pre-flight checks (FR16: validate gh auth upfront)
    validate_gh_auth()
    validate_clean_worktree(repo_root)
    validate_branch_not_behind(repo_root)

    # Warn if PR author differs from authenticated user (prompt injection risk)
    author_warning = check_pr_author_mismatch(pr_number, repo_root)
    if author_warning:
        click.echo(f"[colonyos] {author_warning}", err=True)

    # Create run log for tracking
    ci_run_id = f"ci-fix-{generate_timestamp()}-pr{pr_number}"
    log = RunLog(
        run_id=ci_run_id,
        prompt=f"CI fix for PR #{pr_number}",
        status=RunStatus.RUNNING,
    )

    # Branch name is invariant across retries -- resolve once before the loop.
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10, cwd=repo_root,
    )
    branch_name = branch_result.stdout.strip() or "unknown"

    for attempt in range(1, max_retries + 1):
        click.echo(f"[colonyos] CI fix attempt {attempt}/{max_retries} for PR #{pr_number}")

        # Fetch current checks
        checks = fetch_pr_checks(pr_number, repo_root)
        if all_checks_pass(checks):
            click.echo(f"[colonyos] All CI checks pass on PR #{pr_number}!")
            log.status = RunStatus.COMPLETED
            log.mark_finished()
            _save_run_log(repo_root, log)
            return

        # Collect logs from failed checks (shared helper)
        failures_for_prompt = collect_ci_failure_context(
            checks, repo_root, config.ci_fix.log_char_cap,
        )
        ci_failure_context = format_ci_failures_as_prompt(failures_for_prompt)

        # Build prompt and run agent
        system, user = _build_ci_fix_prompt(
            config, branch_name, ci_failure_context, attempt, max_retries,
        )

        from colonyos.agent import run_phase_sync as _run_phase
        from colonyos.models import Phase
        phase_result = _run_phase(
            Phase.CI_FIX,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.CI_FIX),
            budget_usd=config.budget.per_phase,
            ui=None,
        )
        log.phases.append(phase_result)

        if not phase_result.success:
            click.echo(f"[colonyos] CI fix agent failed: {phase_result.error}", err=True)
            if attempt >= max_retries:
                break
            continue

        click.echo("[colonyos] CI fix agent completed. Pushing changes...")

        # Push the fix commit -- abort on failure to avoid wasting retries
        push_result = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True, timeout=60, cwd=repo_root,
        )
        if push_result.returncode != 0:
            click.echo(
                f"[colonyos] Failed to push: {push_result.stderr.strip()}",
                err=True,
            )
            log.status = RunStatus.COMPLETED
            log.mark_finished()
            _save_run_log(repo_root, log)
            sys.exit(1)

        # If --wait, poll for CI results (unified logic for all attempts)
        if wait:
            click.echo(f"[colonyos] Waiting for CI checks (timeout: {wait_timeout}s)...")
            try:
                final_checks = poll_pr_checks(pr_number, repo_root, timeout=wait_timeout)
                if all_checks_pass(final_checks):
                    click.echo(f"[colonyos] CI checks now pass on PR #{pr_number}!")
                    log.status = RunStatus.COMPLETED
                    log.mark_finished()
                    _save_run_log(repo_root, log)
                    return
                click.echo("[colonyos] CI still failing after fix attempt.")
            except click.ClickException as exc:
                click.echo(f"[colonyos] {exc.message}", err=True)

    # Retries exhausted
    click.echo(
        f"[colonyos] CI fix retries exhausted ({max_retries} attempts) for PR #{pr_number}.",
        err=True,
    )
    log.status = RunStatus.COMPLETED  # Still COMPLETED per FR20, but with success=False phases
    log.mark_finished()
    _save_run_log(repo_root, log)
    sys.exit(1)
