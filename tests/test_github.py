"""Tests for the github module — issue fetching, parsing, and formatting."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from colonyos.github import (
    GitHubIssue,
    _COMMENTS_CHAR_CAP,
    _MAX_COMMENTS,
    fetch_issue,
    fetch_open_issues,
    format_issue_as_prompt,
    parse_issue_ref,
)


# ---------------------------------------------------------------------------
# parse_issue_ref
# ---------------------------------------------------------------------------


class TestParseIssueRef:
    def test_bare_integer(self) -> None:
        assert parse_issue_ref("42") == 42

    def test_bare_integer_with_whitespace(self) -> None:
        assert parse_issue_ref("  42  ") == 42

    def test_full_url(self) -> None:
        assert parse_issue_ref("https://github.com/org/repo/issues/42") == 42

    def test_full_url_with_trailing_slash(self) -> None:
        # URL regex won't match a trailing slash but the number is still captured
        assert parse_issue_ref("https://github.com/org/repo/issues/42") == 42

    def test_https_url(self) -> None:
        assert parse_issue_ref("https://github.com/my-org/my-repo/issues/999") == 999

    def test_http_url(self) -> None:
        assert parse_issue_ref("http://github.com/org/repo/issues/7") == 7

    def test_negative_number_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid issue reference"):
            parse_issue_ref("-1")

    def test_zero_raises(self) -> None:
        # "0" is digit but not positive
        with pytest.raises(ValueError, match="must be positive"):
            parse_issue_ref("0")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid issue reference"):
            parse_issue_ref("abc")

    def test_malformed_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid issue reference"):
            parse_issue_ref("https://github.com/issues/42")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid issue reference"):
            parse_issue_ref("")

    def test_hash_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid issue reference"):
            parse_issue_ref("#42")


# ---------------------------------------------------------------------------
# fetch_issue
# ---------------------------------------------------------------------------


def _make_gh_output(
    number: int = 42,
    title: str = "Add dark mode",
    body: str = "We need dark mode support",
    labels: list[dict] | None = None,
    comments: list[dict] | None = None,
    state: str = "OPEN",
    url: str = "https://github.com/org/repo/issues/42",
) -> str:
    return json.dumps({
        "number": number,
        "title": title,
        "body": body,
        "labels": labels or [],
        "comments": comments or [],
        "state": state,
        "url": url,
    })


class TestFetchIssue:
    @patch("colonyos.github.subprocess.run")
    def test_success(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=_make_gh_output(),
            stderr="",
        )
        issue = fetch_issue(42, tmp_path)
        assert issue.number == 42
        assert issue.title == "Add dark mode"
        assert issue.state == "open"

    @patch("colonyos.github.subprocess.run")
    def test_issue_not_found(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=1,
            stdout="",
            stderr="GraphQL: Could not resolve to an issue or pull request with the number of 999.",
        )
        with pytest.raises(click.ClickException, match="not found"):
            fetch_issue(999, tmp_path)

    @patch("colonyos.github.subprocess.run")
    def test_auth_failure(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=1,
            stdout="",
            stderr="gh auth login required",
        )
        with pytest.raises(click.ClickException, match="colonyos doctor"):
            fetch_issue(42, tmp_path)

    @patch("colonyos.github.subprocess.run")
    def test_timeout(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=10)  # type: ignore[attr-defined]
        with pytest.raises(click.ClickException, match="Timed out"):
            fetch_issue(42, tmp_path)

    @patch("colonyos.github.subprocess.run")
    def test_gh_not_found(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.side_effect = FileNotFoundError()  # type: ignore[attr-defined]
        with pytest.raises(click.ClickException, match="not found"):
            fetch_issue(42, tmp_path)

    @patch("colonyos.github.subprocess.run")
    def test_closed_issue_warns(self, mock_run: object, tmp_path: Path, capsys: object) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=_make_gh_output(state="CLOSED"),
            stderr="",
        )
        issue = fetch_issue(42, tmp_path)
        assert issue.state == "closed"
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "closed" in captured.err.lower()  # type: ignore[attr-defined]

    @patch("colonyos.github.subprocess.run")
    def test_string_ref_parsed(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=_make_gh_output(number=7),
            stderr="",
        )
        issue = fetch_issue("https://github.com/org/repo/issues/7", tmp_path)
        assert issue.number == 7

    @patch("colonyos.github.subprocess.run")
    def test_labels_parsed(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=_make_gh_output(labels=[{"name": "bug"}, {"name": "urgent"}]),
            stderr="",
        )
        issue = fetch_issue(42, tmp_path)
        assert issue.labels == ["bug", "urgent"]

    @patch("colonyos.github.subprocess.run")
    def test_comments_parsed(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=_make_gh_output(comments=[{"body": "me too"}, {"body": "+1"}]),
            stderr="",
        )
        issue = fetch_issue(42, tmp_path)
        assert issue.comments == ["me too", "+1"]


# ---------------------------------------------------------------------------
# format_issue_as_prompt
# ---------------------------------------------------------------------------


class TestFormatIssueAsPrompt:
    def test_basic_issue(self) -> None:
        issue = GitHubIssue(number=42, title="Add dark mode", body="We need it")
        result = format_issue_as_prompt(issue)
        assert "<github_issue>" in result
        assert "</github_issue>" in result
        assert "# #42: Add dark mode" in result
        assert "We need it" in result

    def test_with_labels(self) -> None:
        issue = GitHubIssue(
            number=1, title="Bug", body="Fix it",
            labels=["bug", "critical"],
        )
        result = format_issue_as_prompt(issue)
        assert "`bug`" in result
        assert "`critical`" in result

    def test_with_comments(self) -> None:
        issue = GitHubIssue(
            number=1, title="T", body="B",
            comments=["First comment", "Second comment"],
        )
        result = format_issue_as_prompt(issue)
        assert "## Comments" in result
        assert "First comment" in result
        assert "Second comment" in result

    def test_comment_truncation(self) -> None:
        # Create comments that exceed the character cap
        big_comment = "x" * (_COMMENTS_CHAR_CAP + 100)
        issue = GitHubIssue(
            number=1, title="T", body="B",
            comments=[big_comment],
        )
        result = format_issue_as_prompt(issue)
        assert "[... truncated]" in result

    def test_max_comments_limit(self) -> None:
        comments = [f"Comment {i}" for i in range(_MAX_COMMENTS + 3)]
        issue = GitHubIssue(number=1, title="T", body="B", comments=comments)
        result = format_issue_as_prompt(issue)
        # Should include up to _MAX_COMMENTS
        assert f"Comment {_MAX_COMMENTS - 1}" in result

    def test_empty_body(self) -> None:
        issue = GitHubIssue(number=1, title="Title only", body="")
        result = format_issue_as_prompt(issue)
        assert "# #1: Title only" in result

    def test_preamble_present(self) -> None:
        issue = GitHubIssue(number=1, title="T", body="B")
        result = format_issue_as_prompt(issue)
        assert "source feature description" in result


# ---------------------------------------------------------------------------
# fetch_open_issues
# ---------------------------------------------------------------------------


class TestFetchOpenIssues:
    @patch("colonyos.github.subprocess.run")
    def test_success(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0,
            stdout=json.dumps([
                {"number": 1, "title": "First", "labels": [{"name": "bug"}], "state": "OPEN"},
                {"number": 2, "title": "Second", "labels": [], "state": "OPEN"},
            ]),
            stderr="",
        )
        issues = fetch_open_issues(tmp_path)
        assert len(issues) == 2
        assert issues[0].number == 1
        assert issues[0].labels == ["bug"]

    @patch("colonyos.github.subprocess.run")
    def test_empty_list(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0, stdout="[]", stderr="",
        )
        assert fetch_open_issues(tmp_path) == []

    @patch("colonyos.github.subprocess.run")
    def test_gh_failure_returns_empty(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=1, stdout="", stderr="auth required",
        )
        assert fetch_open_issues(tmp_path) == []

    @patch("colonyos.github.subprocess.run")
    def test_timeout_returns_empty(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=10)  # type: ignore[attr-defined]
        assert fetch_open_issues(tmp_path) == []

    @patch("colonyos.github.subprocess.run")
    def test_file_not_found_returns_empty(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.side_effect = FileNotFoundError()  # type: ignore[attr-defined]
        assert fetch_open_issues(tmp_path) == []

    @patch("colonyos.github.subprocess.run")
    def test_custom_limit(self, mock_run: object, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(  # type: ignore[attr-defined]
            args=[], returncode=0, stdout="[]", stderr="",
        )
        fetch_open_issues(tmp_path, limit=5)
        call_args = mock_run.call_args[0][0]  # type: ignore[attr-defined]
        assert "--limit" in call_args
        idx = call_args.index("--limit")
        assert call_args[idx + 1] == "5"
