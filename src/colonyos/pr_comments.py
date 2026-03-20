"""PR comment fetching, parsing, grouping, and reply posting for ColonyOS.

Uses the ``gh`` CLI for all GitHub API interactions — no new Python
dependencies required. Follows the same subprocess pattern established
in ``github.py`` and ``ci.py``.

.. admonition:: Security — Prompt Injection Risk

   PR review comment content is **untrusted user input** that flows into
   agent prompts executed with ``permission_mode="bypassPermissions"``.
   The same mitigations as GitHub issues apply: XML tag stripping and
   ``<pr_review_comment>`` delimiters with a role-anchoring preamble.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from colonyos.config import GitHubWatchConfig
from colonyos.sanitize import sanitize_untrusted_content

logger = logging.getLogger(__name__)

# Default adjacency threshold for grouping comments (in lines)
DEFAULT_ADJACENCY_THRESHOLD = 10


def validate_file_path(path: str, repo_root: Path | None = None) -> bool:
    """Validate a file path is safe (no path traversal or absolute paths).

    Parameters
    ----------
    path:
        The file path to validate.
    repo_root:
        Optional repository root to validate path is contained within.

    Returns
    -------
    bool
        True if the path is safe, False otherwise.
    """
    if not path:
        return False

    # Reject absolute paths
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        logger.warning("Rejected absolute path in comment: %s", path[:100])
        return False

    # Reject path traversal sequences
    if ".." in path:
        logger.warning("Rejected path traversal in comment: %s", path[:100])
        return False

    # Reject suspicious patterns
    if path.startswith("~") or "~/" in path:
        logger.warning("Rejected home directory path in comment: %s", path[:100])
        return False

    # If repo_root provided, verify path would resolve within it
    if repo_root is not None:
        try:
            resolved = (repo_root / path).resolve()
            repo_resolved = repo_root.resolve()
            # Ensure the resolved path starts with the repo root
            if not str(resolved).startswith(str(repo_resolved)):
                logger.warning(
                    "Path escapes repository root: %s -> %s",
                    path[:100],
                    str(resolved)[:100],
                )
                return False
        except (OSError, ValueError) as exc:
            logger.warning("Path validation error for %s: %s", path[:100], exc)
            return False

    return True


@dataclass
class ReviewComment:
    """Represents a single GitHub PR review comment."""

    id: int
    body: str
    path: str
    line: int
    user_login: str
    user_type: str
    created_at: str
    original_line: int | None = None

    @property
    def is_bot(self) -> bool:
        """Return True if the comment author is a bot."""
        return self.user_type == "Bot"


@dataclass
class CommentGroup:
    """A group of adjacent comments in the same file."""

    path: str
    start_line: int
    end_line: int
    comment_ids: list[int]
    comments: list[ReviewComment] = field(default_factory=list)


def fetch_pr_comments(
    pr_number: int,
    repo_root: Path,
    skip_bot_comments: bool = True,
) -> list[ReviewComment]:
    """Fetch review comments for a PR via ``gh api``.

    Parameters
    ----------
    pr_number:
        The PR number to fetch comments for.
    repo_root:
        Repository root directory (used as ``cwd`` for ``gh``).
    skip_bot_comments:
        If True, filter out comments from bot accounts.

    Returns
    -------
    list[ReviewComment]
        List of review comments.

    Raises
    ------
    click.ClickException
        On ``gh`` errors (auth failure, PR not found, network error).
    """
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments",
                "--paginate",
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
            f"Timed out fetching comments for PR #{pr_number}. Check your network connection."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not found" in stderr.lower():
            raise click.ClickException(
                f"PR #{pr_number} not found in this repository."
            )
        raise click.ClickException(
            f"Failed to fetch comments for PR #{pr_number}: {stderr}. "
            "Run `colonyos doctor` to check GitHub CLI auth."
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse GitHub CLI output for PR #{pr_number} comments: {exc}"
        )

    comments: list[ReviewComment] = []
    for item in data:
        user = item.get("user", {})
        comment = ReviewComment(
            id=item.get("id", 0),
            body=item.get("body", ""),
            path=item.get("path", ""),
            line=item.get("line") or item.get("original_line") or 0,
            original_line=item.get("original_line"),
            user_login=user.get("login", ""),
            user_type=user.get("type", "User"),
            created_at=item.get("created_at", ""),
        )
        if skip_bot_comments and comment.is_bot:
            logger.debug("Skipping bot comment %d from %s", comment.id, comment.user_login)
            continue
        # Validate file path to prevent path traversal
        if not validate_file_path(comment.path, repo_root):
            logger.warning(
                "Skipping comment %d with invalid path: %s",
                comment.id,
                comment.path[:100] if comment.path else "(empty)",
            )
            continue
        comments.append(comment)

    return comments


def group_comments(
    comments: list[ReviewComment],
    adjacency_threshold: int = DEFAULT_ADJACENCY_THRESHOLD,
) -> list[CommentGroup]:
    """Group adjacent comments in the same file.

    Comments within ``adjacency_threshold`` lines of each other in the same
    file are grouped together for batch processing.

    Parameters
    ----------
    comments:
        List of review comments to group.
    adjacency_threshold:
        Maximum line distance for grouping (default: 10).

    Returns
    -------
    list[CommentGroup]
        List of comment groups.
    """
    if not comments:
        return []

    # Sort by (path, line)
    sorted_comments = sorted(comments, key=lambda c: (c.path, c.line))

    groups: list[CommentGroup] = []
    current_group: list[ReviewComment] = [sorted_comments[0]]

    for comment in sorted_comments[1:]:
        last = current_group[-1]
        # Same file and within threshold
        if comment.path == last.path and comment.line - last.line <= adjacency_threshold:
            current_group.append(comment)
        else:
            # Finalize current group and start new one
            groups.append(_create_group(current_group))
            current_group = [comment]

    # Don't forget the last group
    groups.append(_create_group(current_group))

    return groups


def _create_group(comments: list[ReviewComment]) -> CommentGroup:
    """Create a CommentGroup from a list of comments."""
    return CommentGroup(
        path=comments[0].path,
        start_line=min(c.line for c in comments),
        end_line=max(c.line for c in comments),
        comment_ids=[c.id for c in comments],
        comments=list(comments),
    )


def is_allowed_commenter(
    user_login: str,
    config: GitHubWatchConfig,
    repo_root: Path | None = None,
) -> bool:
    """Check if a user is allowed to trigger automatic fixes.

    Parameters
    ----------
    user_login:
        GitHub username of the comment author.
    config:
        GitHubWatchConfig with allowlist settings.
    repo_root:
        Repository root for org membership check (optional).

    Returns
    -------
    bool
        True if the user is allowed.
    """
    # Explicit allowlist takes precedence
    if config.allowed_comment_authors:
        return user_login in config.allowed_comment_authors

    # Fall back to org/repo collaborator check
    if repo_root is None:
        repo_root = Path.cwd()

    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/collaborators/{user_login}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        # 204 No Content or 200 OK means they are a collaborator
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Failed to check collaborator status for %s: %s", user_login, exc)
        return False


def filter_unaddressed_comments(
    comments: list[ReviewComment],
    repo_root: Path,
    marker: str = "<!-- colonyos-response -->",
) -> list[ReviewComment]:
    """Filter out comments that ColonyOS has already addressed.

    A comment is considered addressed if it has a reply containing the
    ColonyOS response marker.

    Parameters
    ----------
    comments:
        List of review comments to filter.
    repo_root:
        Repository root directory.
    marker:
        The marker string to look for in replies.

    Returns
    -------
    list[ReviewComment]
        Comments that have not been addressed.
    """
    unaddressed: list[ReviewComment] = []

    for comment in comments:
        if _has_colonyos_reply(comment.id, repo_root, marker):
            logger.debug("Comment %d already addressed (has marker reply)", comment.id)
            continue
        unaddressed.append(comment)

    return unaddressed


def _has_colonyos_reply(
    comment_id: int,
    repo_root: Path,
    marker: str,
) -> bool:
    """Check if a comment has a reply with the ColonyOS marker."""
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/comments/{comment_id}/replies",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

    if result.returncode != 0:
        return False

    try:
        replies = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False

    for reply in replies:
        body = reply.get("body", "")
        if marker in body:
            return True

    return False


def post_comment_reply(
    comment_id: int,
    body: str,
    repo_root: Path,
    marker: str = "<!-- colonyos-response -->",
) -> bool:
    """Post a reply to a PR review comment.

    Parameters
    ----------
    comment_id:
        The ID of the comment to reply to.
    body:
        The reply body text.
    repo_root:
        Repository root directory.
    marker:
        Marker to prepend for deduplication.

    Returns
    -------
    bool
        True if the reply was posted successfully.
    """
    # Prepend marker for deduplication
    full_body = f"{marker}\n{body}"

    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/comments/{comment_id}/replies",
                "-X", "POST",
                "-F", f"body={full_body}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Failed to post reply to comment %d: %s", comment_id, exc)
        return False

    if result.returncode != 0:
        logger.error(
            "Failed to post reply to comment %d: %s",
            comment_id,
            result.stderr.strip(),
        )
        return False

    return True


def format_pr_comment_as_prompt(
    group: CommentGroup,
    pr_description: str = "",
    prd_context: str = "",
) -> str:
    """Build a structured prompt from a comment group.

    The output is wrapped in ``<pr_review_comment>`` delimiters with a
    preamble instructing the agent to treat it as reviewer feedback.

    All comment content is sanitized to strip XML-like tags.
    """
    parts: list[str] = []

    parts.append(
        "You are a code assistant working on behalf of the engineering team. "
        "The following PR review comment(s) are feedback from a human reviewer. "
        "Your task is to address the feedback by making the requested code changes. "
        "Only make the specific changes requested — do not add unrelated modifications."
    )
    parts.append("")

    parts.append("<pr_review_comment>")
    parts.append(f"File: {group.path}")
    parts.append(f"Lines: {group.start_line}-{group.end_line}")
    parts.append("")

    for comment in group.comments:
        safe_body = sanitize_untrusted_content(comment.body)
        parts.append(f"**Line {comment.line}** (from @{comment.user_login}):")
        parts.append(safe_body)
        parts.append("")

    parts.append("</pr_review_comment>")

    if pr_description:
        parts.append("")
        parts.append("<pr_description>")
        parts.append(sanitize_untrusted_content(pr_description))
        parts.append("</pr_description>")

    if prd_context:
        parts.append("")
        parts.append("<prd_context>")
        parts.append(prd_context)
        parts.append("</prd_context>")

    return "\n".join(parts)


def format_success_reply(commit_sha: str, summary: str) -> str:
    """Format a success reply for a comment.

    Parameters
    ----------
    commit_sha:
        The short SHA of the fix commit.
    summary:
        Brief summary of changes made.

    Returns
    -------
    str
        Formatted reply body (without marker — that's added by post_comment_reply).
    """
    return f"Addressed in commit `{commit_sha}`: {summary}"


def format_failure_reply(run_id: str) -> str:
    """Format a failure reply for a comment.

    Parameters
    ----------
    run_id:
        The ColonyOS run ID for reference.

    Returns
    -------
    str
        Formatted reply body (without marker).
    """
    return (
        "I wasn't able to address this automatically. "
        f"Manual review needed. See run: `{run_id}`"
    )


def fetch_pr_metadata(
    pr_number: int,
    repo_root: Path,
) -> dict[str, Any]:
    """Fetch PR metadata including branch name and description.

    Parameters
    ----------
    pr_number:
        The PR number.
    repo_root:
        Repository root directory.

    Returns
    -------
    dict
        PR metadata with keys: head_branch, base_branch, body, url, author.

    Raises
    ------
    click.ClickException
        On ``gh`` errors.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "headRefName,baseRefName,body,url,author",
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
            f"Timed out fetching PR #{pr_number} metadata."
        )

    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to fetch PR #{pr_number}: {result.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse PR #{pr_number} metadata: {exc}"
        )

    return {
        "head_branch": data.get("headRefName", ""),
        "base_branch": data.get("baseRefName", ""),
        "body": data.get("body", ""),
        "url": data.get("url", ""),
        "author": data.get("author", {}).get("login", ""),
    }


def validate_colonyos_branch(
    branch_name: str,
    branch_prefix: str = "colonyos/",
) -> bool:
    """Check if a branch name matches the ColonyOS branch prefix.

    Parameters
    ----------
    branch_name:
        The branch name to check.
    branch_prefix:
        The expected prefix (default: "colonyos/").

    Returns
    -------
    bool
        True if the branch matches the prefix.
    """
    return branch_name.startswith(branch_prefix)


# ---------------------------------------------------------------------------
# Per-PR rate limiting state
# ---------------------------------------------------------------------------

_MAX_HOURLY_KEYS = 168  # One week of hourly keys


@dataclass
class PRRespondState:
    """Persistent state for per-PR rate limiting."""

    pr_response_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    """Maps PR number to {hour_key: response_count}."""

    aggregate_cost_usd: float = 0.0
    last_updated_iso: str = field(
        default_factory=lambda: ""
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "pr_response_counts": self.pr_response_counts,
            "aggregate_cost_usd": self.aggregate_cost_usd,
            "last_updated_iso": self.last_updated_iso,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PRRespondState":
        """Deserialize state from persistence."""
        return cls(
            pr_response_counts=data.get("pr_response_counts", {}),
            aggregate_cost_usd=data.get("aggregate_cost_usd", 0.0),
            last_updated_iso=data.get("last_updated_iso", ""),
        )

    def get_hourly_count(self, pr_number: int) -> int:
        """Get the response count for a PR in the current hour."""
        from datetime import datetime, timezone
        current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        pr_key = str(pr_number)
        return self.pr_response_counts.get(pr_key, {}).get(current_hour, 0)

    def increment_count(self, pr_number: int) -> None:
        """Increment the response count for a PR in the current hour."""
        from datetime import datetime, timezone
        current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        pr_key = str(pr_number)

        if pr_key not in self.pr_response_counts:
            self.pr_response_counts[pr_key] = {}

        self.pr_response_counts[pr_key][current_hour] = (
            self.pr_response_counts[pr_key].get(current_hour, 0) + 1
        )
        self.last_updated_iso = datetime.now(timezone.utc).isoformat()

        # Prune old hourly keys to prevent unbounded growth
        self._prune_old_hourly_counts()

    def _prune_old_hourly_counts(self) -> None:
        """Remove hourly count keys older than _MAX_HOURLY_KEYS."""
        for pr_key in list(self.pr_response_counts.keys()):
            counts = self.pr_response_counts[pr_key]
            if len(counts) > _MAX_HOURLY_KEYS:
                # Sort keys and keep only the newest
                sorted_keys = sorted(counts.keys(), reverse=True)
                self.pr_response_counts[pr_key] = {
                    k: counts[k] for k in sorted_keys[:_MAX_HOURLY_KEYS]
                }
            # Remove empty PR entries
            if not self.pr_response_counts[pr_key]:
                del self.pr_response_counts[pr_key]

    def check_rate_limit(self, pr_number: int, max_per_hour: int) -> bool:
        """Return True if under the rate limit for this PR."""
        return self.get_hourly_count(pr_number) < max_per_hour


def load_pr_respond_state(repo_root: Path) -> PRRespondState:
    """Load PR respond state from disk, or create new state if not found."""
    from colonyos.config import runs_dir_path

    state_path = runs_dir_path(repo_root) / "pr_respond_state.json"
    if not state_path.exists():
        return PRRespondState()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return PRRespondState.from_dict(data)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load PR respond state: %s", exc)
        return PRRespondState()


def save_pr_respond_state(repo_root: Path, state: PRRespondState) -> None:
    """Save PR respond state to disk."""
    from colonyos.config import runs_dir_path

    state_path = runs_dir_path(repo_root) / "pr_respond_state.json"
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state.to_dict(), indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to save PR respond state: %s", exc)


def get_head_sha(repo_root: Path) -> str | None:
    """Get the current HEAD SHA of the repository.

    Parameters
    ----------
    repo_root:
        Repository root directory.

    Returns
    -------
    str | None
        The short HEAD SHA, or None if unable to determine.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


@dataclass
class ProcessGroupResult:
    """Result of processing a comment group."""

    success: bool
    run_id: str | None
    cost_usd: float
    commit_sha: str | None


def process_comment_group(
    *,
    group: CommentGroup,
    pr_number: int,
    branch_name: str,
    pr_url: str,
    pr_description: str,
    repo_root: Path,
    config: Any,  # ColonyConfig — use Any to avoid circular import
    verbose: bool = False,
    quiet: bool = False,
    expected_head_sha: str | None = None,
) -> ProcessGroupResult:
    """Process a single comment group through the fix pipeline and post replies.

    This is the shared implementation used by both `pr-respond` CLI command
    and `watch --github` mode.

    Parameters
    ----------
    group:
        The comment group to process.
    pr_number:
        The PR number.
    branch_name:
        The branch name.
    pr_url:
        The PR URL.
    pr_description:
        The PR description text.
    repo_root:
        Repository root directory.
    config:
        ColonyConfig instance.
    verbose:
        Whether to stream agent output.
    quiet:
        Whether to suppress output.
    expected_head_sha:
        Optional expected HEAD SHA for force-push defense.

    Returns
    -------
    ProcessGroupResult
        Result with success status, run ID, cost, and commit SHA.
    """
    from colonyos.orchestrator import run_pr_comment_fix

    comment_text = format_pr_comment_as_prompt(group, pr_description=pr_description)

    try:
        log = run_pr_comment_fix(
            pr_number=pr_number,
            branch_name=branch_name,
            file_path=group.path,
            line_range=f"{group.start_line}-{group.end_line}",
            comment_text=comment_text,
            pr_url=pr_url,
            pr_description=pr_description,
            repo_root=repo_root,
            config=config,
            verbose=verbose,
            quiet=quiet,
            expected_head_sha=expected_head_sha,
        )
    except Exception as exc:
        logger.error("Error processing comment group: %s", exc)
        return ProcessGroupResult(
            success=False,
            run_id=None,
            cost_usd=0.0,
            commit_sha=None,
        )

    # Determine success and get commit SHA
    from colonyos.models import RunStatus
    success = log.status == RunStatus.COMPLETED
    commit_sha = get_head_sha(repo_root) if success else None

    # Build and post reply
    if success:
        summary = f"Addressed feedback in {group.path}"
        reply_body = format_success_reply(commit_sha or "unknown", summary)
    else:
        reply_body = format_failure_reply(log.run_id)

    # Post replies to all comments in the group
    marker = config.github_watch.comment_response_marker
    for cid in group.comment_ids:
        post_comment_reply(cid, reply_body, repo_root, marker=marker)

    return ProcessGroupResult(
        success=success,
        run_id=log.run_id,
        cost_usd=log.total_cost_usd,
        commit_sha=commit_sha,
    )
