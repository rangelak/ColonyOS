"""CI log fetching, parsing, prompt formatting, and pre-flight validation.

Uses the ``gh`` CLI for all GitHub Actions interactions — no new Python
dependencies required.  Follows the same subprocess pattern established
in ``github.py``.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import click

from colonyos.sanitize import sanitize_ci_logs

logger = logging.getLogger(__name__)

# Maximum characters of CI log per failed step (tail-biased).
_CI_LOG_CHAR_CAP = 12_000

# Matches full GitHub PR URLs like https://github.com/owner/repo/pull/42
_PR_URL_RE = re.compile(r"https?://github\.com/[^/]+/[^/]+/pull/(\d+)")


def parse_pr_ref(ref: str) -> int:
    """Extract the PR number from a bare integer or full GitHub PR URL.

    Raises :class:`ValueError` for invalid formats.
    """
    ref = ref.strip()
    if ref.isdigit():
        num = int(ref)
        if num <= 0:
            raise ValueError(f"PR number must be positive, got {num}")
        return num
    match = _PR_URL_RE.search(ref)
    if match:
        return int(match.group(1))
    raise ValueError(
        f"Invalid PR reference: {ref!r}. "
        "Accepted formats: 42, https://github.com/owner/repo/pull/42"
    )


@dataclass(frozen=True)
class CheckResult:
    """Represents a single CI check run result."""

    name: str
    state: str
    conclusion: str
    details_url: str = ""


def fetch_pr_checks(pr_number: int, repo_root: Path) -> list[CheckResult]:
    """Fetch check run statuses for a PR via ``gh pr checks``.

    Returns a list of :class:`CheckResult` instances.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "checks", str(pr_number),
                "--json", "name,state,conclusion,detailsUrl",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException(
            f"Timed out fetching PR #{pr_number} checks. Check your network connection."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Failed to fetch checks for PR #{pr_number}: {stderr}. "
            "Run `colonyos doctor` to check GitHub CLI auth."
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse GitHub CLI output for PR #{pr_number} checks: {exc}"
        )

    checks: list[CheckResult] = []
    for item in data:
        checks.append(CheckResult(
            name=item.get("name", ""),
            state=item.get("state", ""),
            conclusion=item.get("conclusion", ""),
            details_url=item.get("detailsUrl", ""),
        ))
    return checks


def extract_run_id_from_url(url: object) -> str | None:
    """Extract the run ID from a GitHub Actions details URL.

    Public API — used by both the CLI and orchestrator modules.
    """
    if not isinstance(url, str):
        return None
    match = re.search(r"/actions/runs/(\d+)", url)
    return match.group(1) if match else None


# Keep private alias for backward compatibility in tests
_extract_run_id_from_url = extract_run_id_from_url


def fetch_check_logs(
    run_id: str,
    repo_root: Path,
    log_char_cap: int = _CI_LOG_CHAR_CAP,
) -> dict[str, str]:
    """Fetch failed check run logs via ``gh run view --log-failed``.

    Returns a dict mapping step name to (truncated) log text.
    Log output is tail-biased: keeps the end where errors appear.
    """
    try:
        result = subprocess.run(
            ["gh", "run", "view", run_id, "--log-failed"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException(
            f"Timed out fetching logs for run {run_id}. The log may be very large."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Failed to fetch logs for run {run_id}: {stderr}"
        )

    return _parse_and_truncate_logs(result.stdout, log_char_cap)


def _parse_and_truncate_logs(
    raw_output: str,
    log_char_cap: int,
) -> dict[str, str]:
    """Parse ``gh run view --log-failed`` output into per-step logs.

    The output format is typically:
        job_name<TAB>step_name<TAB>log_line

    Each step's log is tail-truncated to ``log_char_cap`` characters.
    """
    steps: dict[str, list[str]] = {}
    for line in raw_output.splitlines():
        # gh output uses tab-separated fields: job\tstep\tlog_line
        parts = line.split("\t", 2)
        if len(parts) >= 3:
            step_name = f"{parts[0]} / {parts[1]}"
            steps.setdefault(step_name, []).append(parts[2])
        elif len(parts) == 2:
            step_name = parts[0]
            steps.setdefault(step_name, []).append(parts[1])
        else:
            # Continuation line — append to last step
            if steps:
                last_key = list(steps.keys())[-1]
                steps[last_key].append(line)

    result: dict[str, str] = {}
    for step_name, lines in steps.items():
        full_text = "\n".join(lines)
        result[step_name] = _truncate_tail_biased(full_text, log_char_cap)
    return result


def _truncate_tail_biased(text: str, max_chars: int) -> str:
    """Keep the tail of text (where errors appear), truncating from the top."""
    if len(text) <= max_chars:
        return text
    truncated_lines = text[: -max_chars].count("\n")
    return f"[... {truncated_lines} lines truncated]\n" + text[-max_chars:]


# Maximum total characters across all failure logs injected into the prompt.
# With per-step cap of 12K and up to 20 failing steps, uncapped total could
# reach ~240K — this aggregate cap prevents prompt bloat.
_TOTAL_LOG_CHAR_CAP = 120_000


def format_ci_failures_as_prompt(
    failures: list[dict[str, str]],
    total_char_cap: int = _TOTAL_LOG_CHAR_CAP,
) -> str:
    """Format CI failure context into a structured prompt block.

    Each failure dict has keys: ``name``, ``conclusion``, ``log``.
    Output wraps each in ``<ci_failure_log>`` delimiters with sanitized content.

    An aggregate ``total_char_cap`` limits the total log text injected into
    the prompt across all failures.  When the cap is reached, remaining
    failures are listed by name only.
    """
    parts: list[str] = []
    total_chars = 0
    for failure in failures:
        name = failure.get("name", "unknown")
        conclusion = failure.get("conclusion", "failure")
        log = sanitize_ci_logs(failure.get("log", ""))
        if total_chars + len(log) > total_char_cap and total_chars > 0:
            parts.append(
                f'<ci_failure_log step="{name}" conclusion="{conclusion}">'
            )
            parts.append("[log omitted — aggregate log size cap reached]")
            parts.append("</ci_failure_log>")
            parts.append("")
            continue
        total_chars += len(log)
        parts.append(f'<ci_failure_log step="{name}" conclusion="{conclusion}">')
        parts.append(log)
        parts.append("</ci_failure_log>")
        parts.append("")
    return "\n".join(parts)


def validate_clean_worktree(repo_root: Path) -> None:
    """Raise ``click.ClickException`` if the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise click.ClickException(f"Failed to check git status: {exc}")

    if result.stdout.strip():
        raise click.ClickException(
            "Working tree has uncommitted changes. "
            "Please commit or stash them before running ci-fix."
        )


def validate_branch_not_behind(repo_root: Path) -> None:
    """Raise ``click.ClickException`` if the local branch is behind the remote."""
    try:
        # First fetch to ensure we have the latest remote state
        fetch_result = subprocess.run(
            ["git", "fetch"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_root,
        )
        if fetch_result.returncode != 0:
            logger.warning(
                "git fetch failed (rc=%d): %s — branch-behind check "
                "may use stale data",
                fetch_result.returncode,
                fetch_result.stderr.strip(),
            )
        result = subprocess.run(
            ["git", "rev-list", "HEAD..@{u}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise click.ClickException(f"Failed to check branch status: {exc}")

    # If no upstream is set, rev-list will fail — that's fine, skip the check.
    if result.returncode != 0:
        return

    if result.stdout.strip():
        raise click.ClickException(
            "Local branch is behind the remote. "
            "Please run `git pull` before running ci-fix."
        )


def validate_gh_auth() -> None:
    """Validate that the ``gh`` CLI is authenticated.

    Raises ``click.ClickException`` on failure, directing the user to
    ``colonyos doctor`` — same pattern as ``doctor.py``.
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. "
            "Install it from https://cli.github.com/ then run `colonyos doctor`."
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException(
            "Timed out checking GitHub CLI auth status."
        )

    if result.returncode != 0:
        raise click.ClickException(
            "GitHub CLI is not authenticated. "
            "Run `gh auth login` or `colonyos doctor` to check prerequisites."
        )


def check_pr_author_mismatch(pr_number: int, repo_root: Path) -> str | None:
    """Return a warning message if the PR author differs from the authenticated user.

    Returns ``None`` when authors match or when the check cannot be performed.
    This mitigates prompt injection risk: a malicious PR author could craft CI
    log output to manipulate the agent.
    """
    try:
        # Get PR author
        pr_result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "author", "--jq", ".author.login"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if pr_result.returncode != 0:
            return None
        pr_author = pr_result.stdout.strip()

        # Get authenticated user
        auth_result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=10,
        )
        if auth_result.returncode != 0:
            return None
        auth_user = auth_result.stdout.strip()

        if pr_author and auth_user and pr_author != auth_user:
            return (
                f"WARNING: PR #{pr_number} was authored by @{pr_author}, "
                f"but you are authenticated as @{auth_user}. "
                "CI logs from another user's PR may contain crafted content. "
                "Proceed with caution."
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return None


def collect_ci_failure_context(
    checks: list[CheckResult],
    repo_root: Path,
    log_char_cap: int = _CI_LOG_CHAR_CAP,
) -> list[dict[str, str]]:
    """Collect log details for failed checks into a list of failure dicts.

    Each dict has keys ``name``, ``conclusion``, and ``log``.
    Shared by the CLI ``ci-fix`` command and the orchestrator CI fix loop.
    """
    failed = get_failed_checks(checks)
    failures: list[dict[str, str]] = []
    # Deduplicate by run_id: multiple check results (e.g. matrix builds)
    # can share the same workflow run, so we only fetch logs once per run.
    fetched_logs_by_run_id: dict[str, dict[str, str]] = {}
    for check in failed:
        run_id = extract_run_id_from_url(check.details_url)
        if run_id:
            if run_id not in fetched_logs_by_run_id:
                fetched_logs_by_run_id[run_id] = fetch_check_logs(
                    run_id, repo_root, log_char_cap,
                )
            step_logs = fetched_logs_by_run_id[run_id]
            for step_name, log_text in step_logs.items():
                failures.append({
                    "name": f"{check.name} / {step_name}",
                    "conclusion": check.conclusion,
                    "log": log_text,
                })
        else:
            logger.warning(
                "No GitHub Actions run ID in details URL for check %r: %s",
                check.name, check.details_url,
            )
            failures.append({
                "name": check.name,
                "conclusion": check.conclusion,
                "log": f"(Could not fetch logs — no run ID in URL: {check.details_url})",
            })
    return failures


def poll_pr_checks(
    pr_number: int,
    repo_root: Path,
    timeout: int = 600,
    initial_interval: float = 30.0,
) -> list[CheckResult]:
    """Poll ``gh pr checks`` until all checks complete or timeout.

    Uses exponential backoff: starts at ``initial_interval`` seconds,
    multiplied by 1.5 each iteration, capped at 5 minutes.

    Returns the final list of check results.
    Raises ``click.ClickException`` on timeout.
    """
    start = time.monotonic()
    interval = initial_interval
    max_interval = 300.0  # 5 minutes

    while True:
        checks = fetch_pr_checks(pr_number, repo_root)
        # Check if all are completed (not pending/in_progress).
        # Empty state is NOT treated as terminal — GitHub may return empty
        # state for checks that have not yet started.
        all_done = all(
            c.state.lower() in ("completed", "complete")
            or c.conclusion.lower() in ("success", "failure", "cancelled", "skipped", "timed_out")
            for c in checks
        )
        if all_done and checks:
            return checks

        elapsed = time.monotonic() - start
        if elapsed + interval > timeout:
            raise click.ClickException(
                f"Timed out waiting for CI checks on PR #{pr_number} "
                f"after {int(elapsed)}s."
            )

        click.echo(
            f"  CI checks still running... ({int(elapsed)}s elapsed, "
            f"next poll in {int(interval)}s)",
            err=True,
        )
        time.sleep(interval)
        interval = min(interval * 1.5, max_interval)


def get_failed_checks(checks: list[CheckResult]) -> list[CheckResult]:
    """Filter checks to only those that failed."""
    return [c for c in checks if c.conclusion.lower() == "failure"]


def all_checks_pass(checks: list[CheckResult]) -> bool:
    """Return True if all checks passed (none failed)."""
    return len(get_failed_checks(checks)) == 0
