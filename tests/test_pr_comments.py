"""Tests for PR comment processing module."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import GitHubWatchConfig
from colonyos.pr_comments import (
    CommentGroup,
    PRRespondState,
    ReviewComment,
    fetch_pr_comments,
    filter_unaddressed_comments,
    format_pr_comment_as_prompt,
    group_comments,
    is_allowed_commenter,
    load_pr_respond_state,
    post_comment_reply,
    save_pr_respond_state,
    validate_file_path,
)


@pytest.fixture
def mock_gh_output_comments():
    """Sample gh api output for PR review comments."""
    return json.dumps([
        {
            "id": 123456,
            "body": "Please extract this into a helper function",
            "path": "src/main.py",
            "line": 42,
            "original_line": 42,
            "user": {"login": "reviewer1", "type": "User"},
            "created_at": "2026-03-15T10:00:00Z",
        },
        {
            "id": 123457,
            "body": "Add a docstring here",
            "path": "src/main.py",
            "line": 45,
            "original_line": 45,
            "user": {"login": "reviewer1", "type": "User"},
            "created_at": "2026-03-15T10:01:00Z",
        },
        {
            "id": 123458,
            "body": "Consider using a constant",
            "path": "src/utils.py",
            "line": 10,
            "original_line": 10,
            "user": {"login": "dependabot[bot]", "type": "Bot"},
            "created_at": "2026-03-15T10:02:00Z",
        },
    ])


class TestReviewComment:
    def test_dataclass_fields(self):
        comment = ReviewComment(
            id=123,
            body="Fix this",
            path="src/main.py",
            line=42,
            user_login="reviewer",
            user_type="User",
            created_at="2026-03-15T10:00:00Z",
        )
        assert comment.id == 123
        assert comment.body == "Fix this"
        assert comment.path == "src/main.py"
        assert comment.line == 42
        assert comment.user_login == "reviewer"
        assert comment.user_type == "User"

    def test_is_bot(self):
        bot_comment = ReviewComment(
            id=1, body="", path="", line=0,
            user_login="dependabot[bot]", user_type="Bot",
            created_at="",
        )
        user_comment = ReviewComment(
            id=2, body="", path="", line=0,
            user_login="human", user_type="User",
            created_at="",
        )
        assert bot_comment.is_bot is True
        assert user_comment.is_bot is False


class TestFetchPRComments:
    def test_fetches_and_parses_comments(self, tmp_path: Path, mock_gh_output_comments):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_gh_output_comments,
                stderr="",
            )
            # skip_bot_comments=False to get all 3 comments
            comments = fetch_pr_comments(42, tmp_path, skip_bot_comments=False)

        assert len(comments) == 3
        assert comments[0].id == 123456
        assert comments[0].body == "Please extract this into a helper function"
        assert comments[0].path == "src/main.py"
        assert comments[0].line == 42
        assert comments[0].user_login == "reviewer1"

    def test_filters_bot_comments_when_configured(self, tmp_path: Path, mock_gh_output_comments):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_gh_output_comments,
                stderr="",
            )
            comments = fetch_pr_comments(42, tmp_path, skip_bot_comments=True)

        # Should filter out the bot comment
        assert len(comments) == 2
        assert all(c.user_type != "Bot" for c in comments)

    def test_includes_bot_comments_when_not_filtered(self, tmp_path: Path, mock_gh_output_comments):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_gh_output_comments,
                stderr="",
            )
            comments = fetch_pr_comments(42, tmp_path, skip_bot_comments=False)

        assert len(comments) == 3

    def test_handles_api_error(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Resource not found",
            )
            with pytest.raises(Exception) as exc_info:
                fetch_pr_comments(42, tmp_path)
            assert "not found" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()


class TestGroupComments:
    def test_groups_adjacent_comments_same_file(self):
        comments = [
            ReviewComment(id=1, body="Fix A", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
            ReviewComment(id=2, body="Fix B", path="src/main.py", line=15,
                         user_login="r1", user_type="User", created_at=""),
            ReviewComment(id=3, body="Fix C", path="src/main.py", line=18,
                         user_login="r1", user_type="User", created_at=""),
        ]
        groups = group_comments(comments, adjacency_threshold=10)

        # All within 10 lines of each other, should be one group
        assert len(groups) == 1
        assert len(groups[0].comment_ids) == 3
        assert groups[0].path == "src/main.py"
        assert groups[0].start_line == 10
        assert groups[0].end_line == 18

    def test_separates_distant_comments(self):
        comments = [
            ReviewComment(id=1, body="Fix A", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
            ReviewComment(id=2, body="Fix B", path="src/main.py", line=50,
                         user_login="r1", user_type="User", created_at=""),
        ]
        groups = group_comments(comments, adjacency_threshold=10)

        # More than 10 lines apart, should be two groups
        assert len(groups) == 2

    def test_separates_comments_different_files(self):
        comments = [
            ReviewComment(id=1, body="Fix A", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
            ReviewComment(id=2, body="Fix B", path="src/utils.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
        ]
        groups = group_comments(comments)

        assert len(groups) == 2

    def test_empty_comments_returns_empty(self):
        groups = group_comments([])
        assert groups == []

    def test_single_comment_returns_single_group(self):
        comments = [
            ReviewComment(id=1, body="Fix", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
        ]
        groups = group_comments(comments)

        assert len(groups) == 1
        assert groups[0].comment_ids == [1]


class TestIsAllowedCommenter:
    def test_explicit_allowlist_match(self):
        config = GitHubWatchConfig(allowed_comment_authors=["alice", "bob"])
        assert is_allowed_commenter("alice", config) is True
        assert is_allowed_commenter("bob", config) is True
        assert is_allowed_commenter("charlie", config) is False

    def test_empty_allowlist_falls_back_to_org_check(self, tmp_path: Path):
        config = GitHubWatchConfig(allowed_comment_authors=[])
        with patch("subprocess.run") as mock_run:
            # Simulate successful org membership check
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr="",
            )
            result = is_allowed_commenter("alice", config, repo_root=tmp_path)
        assert result is True

    def test_org_check_failure_rejects(self, tmp_path: Path):
        config = GitHubWatchConfig(allowed_comment_authors=[])
        with patch("subprocess.run") as mock_run:
            # Simulate failed org membership check (404)
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="HTTP 404",
            )
            result = is_allowed_commenter("external_user", config, repo_root=tmp_path)
        assert result is False


class TestFilterUnaddressedComments:
    def test_filters_comments_with_marker_reply(self):
        comments = [
            ReviewComment(id=1, body="Fix A", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
            ReviewComment(id=2, body="Fix B", path="src/main.py", line=20,
                         user_login="r1", user_type="User", created_at=""),
        ]
        # Simulate: comment 1 has a ColonyOS reply, comment 2 does not
        with patch("subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "1/replies" in str(cmd):
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps([{"body": "<!-- colonyos-response -->\nFixed in abc123"}]),
                        stderr="",
                    )
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps([]),
                    stderr="",
                )
            mock_run.side_effect = side_effect

            unaddressed = filter_unaddressed_comments(
                comments,
                Path("."),
                marker="<!-- colonyos-response -->",
            )

        assert len(unaddressed) == 1
        assert unaddressed[0].id == 2

    def test_no_replies_all_unaddressed(self):
        comments = [
            ReviewComment(id=1, body="Fix A", path="src/main.py", line=10,
                         user_login="r1", user_type="User", created_at=""),
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([]),
                stderr="",
            )
            unaddressed = filter_unaddressed_comments(
                comments, Path("."), marker="<!-- colonyos-response -->"
            )

        assert len(unaddressed) == 1


class TestPostCommentReply:
    def test_successful_reply(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="{}",
                stderr="",
            )
            result = post_comment_reply(
                comment_id=123,
                body="Fixed in commit abc123",
                repo_root=tmp_path,
                marker="<!-- colonyos-response -->",
            )

        assert result is True
        # Verify the marker was prepended in the -F body argument
        call_args = mock_run.call_args
        cmd = call_args.args[0]
        # The -F flag passes the body; find the body=... argument
        body_args = [arg for arg in cmd if arg.startswith("body=")]
        assert len(body_args) == 1
        assert "<!-- colonyos-response -->" in body_args[0]

    def test_failed_reply(self, tmp_path: Path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Rate limit exceeded",
            )
            result = post_comment_reply(
                comment_id=123,
                body="Fixed",
                repo_root=tmp_path,
            )

        assert result is False


class TestFormatPRCommentAsPrompt:
    def test_formats_single_comment(self):
        group = CommentGroup(
            path="src/main.py",
            start_line=42,
            end_line=42,
            comment_ids=[123],
            comments=[
                ReviewComment(id=123, body="Extract this into a helper",
                             path="src/main.py", line=42,
                             user_login="reviewer", user_type="User", created_at=""),
            ],
        )
        prompt = format_pr_comment_as_prompt(group, pr_description="Add new feature")

        assert "src/main.py" in prompt
        assert "42" in prompt
        assert "Extract this into a helper" in prompt
        assert "<pr_review_comment>" in prompt
        assert "</pr_review_comment>" in prompt

    def test_formats_multiple_comments(self):
        group = CommentGroup(
            path="src/main.py",
            start_line=42,
            end_line=50,
            comment_ids=[123, 124],
            comments=[
                ReviewComment(id=123, body="Comment 1",
                             path="src/main.py", line=42,
                             user_login="r1", user_type="User", created_at=""),
                ReviewComment(id=124, body="Comment 2",
                             path="src/main.py", line=50,
                             user_login="r1", user_type="User", created_at=""),
            ],
        )
        prompt = format_pr_comment_as_prompt(group, pr_description="")

        assert "Comment 1" in prompt
        assert "Comment 2" in prompt

    def test_sanitizes_comment_content(self):
        group = CommentGroup(
            path="src/main.py",
            start_line=42,
            end_line=42,
            comment_ids=[123],
            comments=[
                ReviewComment(id=123, body="<script>alert('xss')</script>Fix this",
                             path="src/main.py", line=42,
                             user_login="r1", user_type="User", created_at=""),
            ],
        )
        prompt = format_pr_comment_as_prompt(group, pr_description="")

        # XML tags should be stripped
        assert "<script>" not in prompt
        assert "Fix this" in prompt


class TestValidateFilePath:
    """Tests for file path validation (path traversal defense)."""

    def test_valid_relative_path(self):
        assert validate_file_path("src/main.py") is True
        assert validate_file_path("test/test_main.py") is True
        assert validate_file_path("README.md") is True

    def test_rejects_absolute_paths(self):
        assert validate_file_path("/etc/passwd") is False
        assert validate_file_path("/home/user/file.txt") is False

    def test_rejects_windows_absolute_paths(self):
        assert validate_file_path("C:\\Windows\\System32") is False

    def test_rejects_path_traversal(self):
        assert validate_file_path("../secrets.txt") is False
        assert validate_file_path("foo/../../../etc/passwd") is False
        assert validate_file_path("..") is False

    def test_rejects_home_directory_references(self):
        assert validate_file_path("~/secret.txt") is False
        assert validate_file_path("foo/~/bar") is False

    def test_rejects_empty_path(self):
        assert validate_file_path("") is False

    def test_validates_against_repo_root(self, tmp_path: Path):
        # Create a test file
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()

        # Valid path within repo
        assert validate_file_path("src/main.py", tmp_path) is True

        # Path traversal should fail even with repo root check
        assert validate_file_path("../outside.txt", tmp_path) is False


class TestPRRespondState:
    """Tests for PR respond rate limiting state."""

    def test_initial_state(self):
        state = PRRespondState()
        assert state.get_hourly_count(42) == 0
        assert state.aggregate_cost_usd == 0.0

    def test_increment_count(self):
        state = PRRespondState()
        state.increment_count(42)
        assert state.get_hourly_count(42) == 1

        state.increment_count(42)
        assert state.get_hourly_count(42) == 2

    def test_check_rate_limit(self):
        state = PRRespondState()
        assert state.check_rate_limit(42, max_per_hour=3) is True

        state.increment_count(42)
        state.increment_count(42)
        state.increment_count(42)

        # Should be at limit now
        assert state.check_rate_limit(42, max_per_hour=3) is False

    def test_separate_pr_counts(self):
        state = PRRespondState()
        state.increment_count(42)
        state.increment_count(42)
        state.increment_count(43)

        assert state.get_hourly_count(42) == 2
        assert state.get_hourly_count(43) == 1

    def test_serialization(self):
        state = PRRespondState()
        state.increment_count(42)
        state.aggregate_cost_usd = 1.5

        data = state.to_dict()
        restored = PRRespondState.from_dict(data)

        assert restored.get_hourly_count(42) == 1
        assert restored.aggregate_cost_usd == 1.5

    def test_persistence(self, tmp_path: Path):
        # Create runs directory
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)

        state = PRRespondState()
        state.increment_count(42)
        state.aggregate_cost_usd = 2.5

        save_pr_respond_state(tmp_path, state)

        loaded = load_pr_respond_state(tmp_path)
        assert loaded.get_hourly_count(42) == 1
        assert loaded.aggregate_cost_usd == 2.5

    def test_load_missing_file_returns_new_state(self, tmp_path: Path):
        # Create runs directory but no state file
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)

        state = load_pr_respond_state(tmp_path)
        assert state.get_hourly_count(42) == 0


class TestFetchPRCommentsPathValidation:
    """Tests for path validation in fetch_pr_comments."""

    def test_skips_comments_with_invalid_paths(self, tmp_path: Path):
        """Test that comments with invalid paths are filtered out."""
        comments_json = json.dumps([
            {
                "id": 1,
                "body": "Valid path comment",
                "path": "src/main.py",
                "line": 10,
                "user": {"login": "user1", "type": "User"},
                "created_at": "2026-03-15T10:00:00Z",
            },
            {
                "id": 2,
                "body": "Path traversal attempt",
                "path": "../../../etc/passwd",
                "line": 1,
                "user": {"login": "attacker", "type": "User"},
                "created_at": "2026-03-15T10:01:00Z",
            },
            {
                "id": 3,
                "body": "Absolute path attempt",
                "path": "/etc/shadow",
                "line": 1,
                "user": {"login": "attacker", "type": "User"},
                "created_at": "2026-03-15T10:02:00Z",
            },
        ])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=comments_json,
                stderr="",
            )

            comments = fetch_pr_comments(42, tmp_path, skip_bot_comments=False)

            # Only the valid path comment should be returned
            assert len(comments) == 1
            assert comments[0].id == 1
            assert comments[0].path == "src/main.py"
