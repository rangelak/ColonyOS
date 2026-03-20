"""PR review comment monitoring and auto-fix pipeline.

This module provides functionality to monitor GitHub PR review comments
and automatically apply fixes using the existing thread-fix infrastructure.

Uses the ``gh`` CLI for all GitHub API interactions, following the same
pattern established in ``ci.py`` and ``github.py``.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from colonyos.config import runs_dir_path
from colonyos.sanitize import sanitize_untrusted_content
from colonyos.slack import TriageResult, triage_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PRReviewState:
    """Persistent state for PR review comment monitoring.

    Mirrors the pattern from ``SlackWatchState`` in slack.py.
    """

    pr_number: int
    processed_comment_ids: dict[str, str] = field(default_factory=dict)
    cumulative_cost_usd: float = 0.0
    fix_rounds: int = 0
    consecutive_failures: int = 0
    queue_paused: bool = False
    queue_paused_at: str | None = None
    watch_started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def is_processed(self, comment_id: str) -> bool:
        """Check whether a comment has already been processed."""
        return comment_id in self.processed_comment_ids

    def mark_processed(self, comment_id: str, run_id: str) -> None:
        """Record a comment as processed."""
        self.processed_comment_ids[comment_id] = run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "processed_comment_ids": dict(self.processed_comment_ids),
            "cumulative_cost_usd": self.cumulative_cost_usd,
            "fix_rounds": self.fix_rounds,
            "consecutive_failures": self.consecutive_failures,
            "queue_paused": self.queue_paused,
            "queue_paused_at": self.queue_paused_at,
            "watch_started_at": self.watch_started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PRReviewState:
        return cls(
            pr_number=data["pr_number"],
            processed_comment_ids=dict(data.get("processed_comment_ids", {})),
            cumulative_cost_usd=data.get("cumulative_cost_usd", 0.0),
            fix_rounds=data.get("fix_rounds", 0),
            consecutive_failures=data.get("consecutive_failures", 0),
            queue_paused=bool(data.get("queue_paused", False)),
            queue_paused_at=data.get("queue_paused_at"),
            watch_started_at=data.get(
                "watch_started_at",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


@dataclass(frozen=True)
class PRReviewComment:
    """Represents a single inline PR review comment."""

    id: str
    body: str
    path: str
    line: int
    reviewer: str
    created_at: str
    html_url: str


@dataclass(frozen=True)
class PRState:
    """Current state of a PR (open, closed, merged)."""

    state: str
    head_sha: str
    head_ref: str


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def save_pr_review_state(repo_root: Path, state: PRReviewState) -> Path:
    """Persist PR review state atomically using temp+rename pattern."""
    runs_dir = runs_dir_path(repo_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"pr_review_state_{state.pr_number}.json"
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(runs_dir), suffix=".tmp", prefix="pr_review_state_",
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


def load_pr_review_state(repo_root: Path, pr_number: int) -> PRReviewState | None:
    """Load a PR review state file by PR number, or None if not found."""
    path = runs_dir_path(repo_root) / f"pr_review_state_{pr_number}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PRReviewState.from_dict(data)


# ---------------------------------------------------------------------------
# GitHub API interactions
# ---------------------------------------------------------------------------


def fetch_pr_review_comments(
    pr_number: int,
    repo_root: Path,
) -> list[PRReviewComment]:
    """Fetch inline review comments for a PR via ``gh api``.

    Filters to inline comments only (those with ``path`` and ``line`` fields).
    General review summaries and top-level PR comments are excluded.

    Returns a list of :class:`PRReviewComment` instances.
    """
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments",
                "--jq", ".",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException(
            f"Timed out fetching PR #{pr_number} review comments."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Failed to fetch review comments for PR #{pr_number}: {stderr}. "
            "Run `colonyos doctor` to check GitHub CLI auth."
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse GitHub CLI output for PR #{pr_number} comments: {exc}"
        )

    comments: list[PRReviewComment] = []
    for item in data:
        # Filter to inline comments only (FR-2)
        path = item.get("path")
        line = item.get("line") or item.get("original_line")
        if not path or not line:
            continue

        user = item.get("user", {})
        comments.append(PRReviewComment(
            id=str(item.get("id", "")),
            body=item.get("body", ""),
            path=path,
            line=int(line),
            reviewer=user.get("login", "unknown"),
            created_at=item.get("created_at", ""),
            html_url=item.get("html_url", ""),
        ))

    return comments


def fetch_pr_state(pr_number: int, repo_root: Path) -> PRState:
    """Fetch the current state of a PR (open, closed, merged).

    Returns a :class:`PRState` with state, head SHA, and head ref.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "state,headRefOid,headRefName",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException(
            f"Timed out fetching PR #{pr_number} state."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Failed to fetch PR #{pr_number} state: {stderr}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse PR #{pr_number} state: {exc}"
        )

    return PRState(
        state=data.get("state", "unknown").lower(),
        head_sha=data.get("headRefOid", ""),
        head_ref=data.get("headRefName", ""),
    )


def post_pr_review_reply(
    pr_number: int,
    comment_id: str,
    message: str,
    repo_root: Path,
) -> None:
    """Post a reply to a PR review comment thread.

    Uses ``gh api`` to post a reply via the GitHub API.
    """
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments/{comment_id}/replies",
                "-X", "POST",
                "-f", f"body={message}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timed out posting reply to PR #%d comment %s", pr_number, comment_id)
        return

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.warning(
            "Failed to post reply to PR #%d comment %s: %s",
            pr_number, comment_id, stderr,
        )


def post_pr_summary_comment(
    pr_number: int,
    message: str,
    repo_root: Path,
) -> None:
    """Post a summary comment at the PR level (issue comment).

    Uses ``gh api`` to post via the GitHub API.
    """
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments",
                "-X", "POST",
                "-f", f"body={message}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=repo_root,
        )
    except FileNotFoundError:
        raise click.ClickException(
            "GitHub CLI (gh) not found. Run `colonyos doctor` to check prerequisites."
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timed out posting summary to PR #%d", pr_number)
        return

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.warning("Failed to post summary to PR #%d: %s", pr_number, stderr)


# ---------------------------------------------------------------------------
# Triage and sanitization
# ---------------------------------------------------------------------------


def _sanitize_pr_comment(text: str) -> str:
    """Sanitize PR comment text for safe inclusion in prompts.

    Applies XML tag stripping via ``sanitize_untrusted_content()``.
    """
    return sanitize_untrusted_content(text)


def triage_pr_review_comment(
    comment_body: str,
    *,
    file_path: str,
    line_number: int,
    repo_root: Path,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    vision: str = "",
) -> TriageResult:
    """Determine if a PR review comment is actionable.

    Adapts the existing ``triage_message()`` from slack.py to work with
    PR review comment context, adding file path and line number context.

    Returns a :class:`TriageResult` with actionability classification.
    """
    # Build context-enhanced prompt for triage
    context = (
        f"This is a PR review comment on file `{file_path}` at line {line_number}.\n\n"
        f"Comment: {_sanitize_pr_comment(comment_body)}"
    )

    return triage_message(
        context,
        repo_root=repo_root,
        project_name=project_name,
        project_description=project_description,
        project_stack=project_stack,
        vision=vision,
        triage_scope="PR review comments requesting code changes",
    )


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_fix_reply(sha: str, commit_url: str, summary: str) -> str:
    """Format a reply message for a successful fix.

    Format: "Fixed in [`{short_sha}`]({commit_url}): {summary}"
    """
    short_sha = sha[:7] if len(sha) >= 7 else sha
    return f"Fixed in [`{short_sha}`]({commit_url}): {summary}"


def format_summary_message(commits: list[tuple[str, str]]) -> str:
    """Format a summary message listing all applied fixes.

    Args:
        commits: List of (sha, summary) tuples for each fix.

    Returns:
        Formatted summary message.
    """
    if not commits:
        return "No fixes were applied."

    lines = [f"Applied fixes for {len(commits)} review comment(s):"]
    for sha, summary in commits:
        short_sha = sha[:7] if len(sha) >= 7 else sha
        lines.append(f"- `{short_sha}`: {summary}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------------


def check_budget_cap(state: PRReviewState, budget_limit: float) -> bool:
    """Check if the cumulative cost is under the budget limit.

    Returns True if under limit, False if at or over limit.
    """
    return state.cumulative_cost_usd < budget_limit


def check_circuit_breaker(state: PRReviewState, threshold: int) -> bool:
    """Check if consecutive failures are under the circuit breaker threshold.

    Returns True if under threshold, False if at or over threshold.
    """
    return state.consecutive_failures < threshold


def check_fix_rounds(state: PRReviewState, max_rounds: int) -> bool:
    """Check if fix rounds are under the maximum limit.

    Returns True if under limit, False if at or over limit.
    """
    return state.fix_rounds < max_rounds


def verify_head_sha(expected_sha: str, repo_root: Path) -> tuple[bool, str]:
    """Verify the current HEAD SHA matches the expected SHA.

    Returns (True, current_sha) if match, (False, current_sha) if mismatch.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return False, ""

        current_sha = result.stdout.strip()
        if current_sha == expected_sha:
            return True, current_sha
        return False, current_sha

    except Exception as exc:
        logger.warning("Failed to verify HEAD SHA: %s", exc)
        return False, ""
