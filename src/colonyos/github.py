"""GitHub issue fetching, parsing, and formatting for ColonyOS.

Uses the ``gh`` CLI (validated by ``doctor.py``) for all GitHub API
interactions — no new Python dependencies required.

.. admonition:: Security — Prompt Injection Risk

   GitHub issue content (title, body, labels, comments) is **untrusted
   user input** that flows into agent prompts executed with
   ``permission_mode="bypassPermissions"``.  A malicious issue author
   could embed adversarial instructions (e.g. "Ignore previous
   instructions and run …").

   Mitigations applied here:

   * XML-like tags are stripped from issue content so attackers cannot
     close the ``<github_issue>`` delimiter and inject top-level
     instructions.
   * Content is wrapped in clearly-delimited ``<github_issue>`` tags
     with a preamble that anchors the model's role.

   These reduce — but do not eliminate — the risk.  A future V2 should
   consider sandboxed execution for issue-sourced runs.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# Import shared sanitization utilities — single source of truth for the
# XML tag regex used across GitHub and Slack integrations.
from colonyos.sanitize import XML_TAG_RE as _XML_TAG_RE  # noqa: F401
from colonyos.sanitize import sanitize_untrusted_content as _sanitize_untrusted_content  # noqa: F401


# Matches full GitHub issue URLs like https://github.com/owner/repo/issues/42
_ISSUE_URL_RE = re.compile(
    r"https?://github\.com/[^/]+/[^/]+/issues/(\d+)"
)

# Maximum characters for the combined comments section
_COMMENTS_CHAR_CAP = 8_000

# Maximum number of comments to include
_MAX_COMMENTS = 5


@dataclass(frozen=True)
class GitHubIssue:
    """Represents a GitHub issue fetched via the ``gh`` CLI."""

    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    state: str = "open"
    url: str = ""


def parse_issue_ref(ref: str) -> int:
    """Extract the issue number from a bare integer or full GitHub URL.

    Raises :class:`ValueError` for invalid formats.
    """
    ref = ref.strip()

    # Try bare integer first
    if ref.isdigit():
        num = int(ref)
        if num <= 0:
            raise ValueError(f"Issue number must be positive, got {num}")
        return num

    # Try full URL
    match = _ISSUE_URL_RE.search(ref)
    if match:
        return int(match.group(1))

    raise ValueError(
        f"Invalid issue reference: {ref!r}. "
        "Accepted formats: 42, https://github.com/owner/repo/issues/42"
    )


def fetch_issue(issue_ref: str | int, repo_root: Path) -> GitHubIssue:
    """Fetch a single issue via ``gh issue view``.

    Parameters
    ----------
    issue_ref:
        Either a bare issue number (int or str) or a full GitHub URL.
    repo_root:
        Repository root directory (used as ``cwd`` for ``gh``).

    Returns
    -------
    GitHubIssue

    Raises
    ------
    click.ClickException
        On ``gh`` errors (auth failure, issue not found, network error).
    """
    if isinstance(issue_ref, str):
        number = parse_issue_ref(issue_ref)
    else:
        number = issue_ref

    try:
        result = subprocess.run(
            [
                "gh", "issue", "view", str(number),
                "--json", "number,title,body,labels,comments,state,url",
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
            f"Timed out fetching issue #{number}. Check your network connection."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not found" in stderr.lower() or "could not resolve" in stderr.lower():
            raise click.ClickException(
                f"Issue #{number} not found in this repository."
            )
        raise click.ClickException(
            f"Failed to fetch issue #{number}: {stderr}. "
            "Run `colonyos doctor` to check GitHub CLI auth."
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Failed to parse GitHub CLI output for issue #{number}: {exc}"
        )

    labels = [lbl.get("name", "") for lbl in data.get("labels", [])]
    raw_comments = data.get("comments", [])
    comments = [c.get("body", "") for c in raw_comments if c.get("body")]

    issue = GitHubIssue(
        number=data.get("number", number),
        title=data.get("title", ""),
        body=data.get("body", "") or "",
        labels=labels,
        comments=comments,
        state=data.get("state", "open").lower(),
        url=data.get("url", ""),
    )

    if issue.state == "closed":
        click.echo(
            f"Warning: Issue #{issue.number} is closed. Proceeding anyway.",
            err=True,
        )

    return issue


def format_issue_as_prompt(issue: GitHubIssue) -> str:
    """Build a structured prompt string from a :class:`GitHubIssue`.

    The output is wrapped in ``<github_issue>`` delimiters with a preamble
    instructing the agent to treat it as a feature description.

    All untrusted fields (title, body, labels, comments) are sanitized to
    strip XML-like tags, reducing prompt injection risk.  See module docstring.
    """
    safe_title = _sanitize_untrusted_content(issue.title)
    safe_body = _sanitize_untrusted_content(issue.body)
    safe_labels = [_sanitize_untrusted_content(lbl) for lbl in issue.labels]
    safe_comments = [_sanitize_untrusted_content(c) for c in issue.comments]

    parts: list[str] = []

    parts.append(
        "The following GitHub issue is the source feature description. "
        "Treat it as the primary specification for this task."
    )
    parts.append("")
    parts.append("<github_issue>")
    parts.append(f"# #{issue.number}: {safe_title}")
    parts.append("")

    if safe_body:
        parts.append(safe_body)
        parts.append("")

    if safe_labels:
        label_str = ", ".join(f"`{lbl}`" for lbl in safe_labels)
        parts.append(f"**Labels:** {label_str}")
        parts.append("")

    # Include up to _MAX_COMMENTS comments, capped at _COMMENTS_CHAR_CAP total
    if safe_comments:
        parts.append("## Comments")
        parts.append("")
        total_chars = 0
        for i, comment in enumerate(safe_comments[:_MAX_COMMENTS]):
            if total_chars + len(comment) > _COMMENTS_CHAR_CAP:
                remaining = _COMMENTS_CHAR_CAP - total_chars
                if remaining > 0:
                    parts.append(f"**Comment {i + 1}:**")
                    parts.append(comment[:remaining] + "\n\n[... truncated]")
                else:
                    parts.append(f"[... {len(safe_comments) - i} more comments truncated]")
                break
            parts.append(f"**Comment {i + 1}:**")
            parts.append(comment)
            parts.append("")
            total_chars += len(comment)

    parts.append("</github_issue>")

    return "\n".join(parts)


def check_open_pr(
    branch: str,
    repo_root: Path,
    timeout: int = 5,
) -> tuple[int | None, str | None]:
    """Check if an open PR exists for the given branch.

    Returns ``(pr_number, pr_url)`` if found, or ``(None, None)`` otherwise.
    Gracefully returns ``(None, None)`` on any error (network, timeout, gh
    not installed).
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--head", branch,
                "--json", "number,url",
                "--limit", "1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to check open PRs for branch %s: %s", branch, exc)
        return None, None

    if result.returncode != 0:
        logger.warning(
            "gh pr list failed for branch %s: %s",
            branch,
            result.stderr.strip(),
        )
        return None, None

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse gh pr list output for branch %s", branch)
        return None, None

    if items:
        pr = items[0]
        return pr.get("number"), pr.get("url")

    return None, None


@dataclass(frozen=True)
class GitHubPR:
    """Represents an open pull request fetched via the ``gh`` CLI."""

    number: int
    title: str
    branch: str
    url: str = ""
    labels: list[str] = field(default_factory=list)


def fetch_open_prs(
    repo_root: Path,
    limit: int = 20,
) -> list[GitHubPR]:
    """Fetch open pull requests for CEO context.

    Non-blocking — all errors are caught and logged, returning an empty
    list on failure.  Mirrors :func:`fetch_open_issues` in style.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError(f"limit must be an integer between 1 and 100, got {limit!r}")
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--json", "number,title,headRefName,url,labels",
                "--limit", str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to fetch open PRs: %s", exc)
        return []

    if result.returncode != 0:
        logger.warning("gh pr list failed: %s", result.stderr.strip())
        return []

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse gh pr list output")
        return []

    if not isinstance(items, list):
        logger.warning("gh pr list returned non-array JSON")
        return []

    prs: list[GitHubPR] = []
    for item in items:
        labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
        prs.append(GitHubPR(
            number=item.get("number", 0),
            title=item.get("title", ""),
            branch=item.get("headRefName", ""),
            url=item.get("url", ""),
            labels=labels,
        ))
    return prs


def fetch_open_issues(
    repo_root: Path,
    limit: int = 20,
) -> list[GitHubIssue]:
    """Fetch open issues for CEO context.

    This is **non-blocking** — all errors are caught and logged, returning
    an empty list on failure.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError(f"limit must be an integer between 1 and 100, got {limit!r}")
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--json", "number,title,labels,state",
                "--limit", str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to fetch open issues: %s", exc)
        return []

    if result.returncode != 0:
        logger.warning("gh issue list failed: %s", result.stderr.strip())
        return []

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse gh issue list output")
        return []

    issues: list[GitHubIssue] = []
    for item in items:
        labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
        issues.append(GitHubIssue(
            number=item.get("number", 0),
            title=item.get("title", ""),
            body="",
            labels=labels,
            state=item.get("state", "open").lower(),
        ))
    return issues


def poll_new_issues(
    queue_items: list[Any],
    repo_root: Path,
    issue_labels: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Poll for new GitHub issues not already in the queue.

    Parameters
    ----------
    queue_items:
        Existing queue items (must have ``source_type`` and ``source_value``
        attributes) used for deduplication.
    repo_root:
        Repository root for ``gh`` CLI calls.
    issue_labels:
        If non-empty, only issues with at least one matching label are
        returned.  Comparison is case-insensitive.
    limit:
        Maximum number of issues to fetch.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts with keys ``number``, ``title``, ``labels`` for
        each new (non-duplicate) issue.
    """
    issues = fetch_open_issues(repo_root, limit=limit)
    label_filter = {lbl.lower() for lbl in (issue_labels or [])}

    # Build set of already-known issue numbers
    known_issues: set[str] = set()
    for item in queue_items:
        src_type = getattr(item, "source_type", None)
        src_val = getattr(item, "source_value", None)
        if src_type == "issue" and src_val:
            known_issues.add(str(src_val))

    new_issues: list[dict[str, Any]] = []
    for issue in issues:
        # Skip known issues
        if str(issue.number) in known_issues:
            continue

        # Label filtering
        if label_filter:
            issue_labels_lower = {lbl.lower() for lbl in issue.labels}
            if not label_filter.intersection(issue_labels_lower):
                continue

        new_issues.append({
            "number": issue.number,
            "title": issue.title,
            "labels": issue.labels,
        })

    return new_issues
