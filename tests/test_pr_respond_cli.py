"""Tests for the colonyos pr-respond CLI command."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from colonyos.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_config_file(tmp_path: Path) -> Path:
    """Create a minimal config file for testing."""
    colonyos_dir = tmp_path / ".colonyos"
    colonyos_dir.mkdir()
    config = {
        "project": {"name": "test", "description": "test", "stack": "python"},
        "personas": [],
        "branch_prefix": "colonyos/",
        "github_watch": {
            "enabled": False,
            "max_responses_per_pr_per_hour": 3,
            "skip_bot_comments": True,
            "comment_response_marker": "<!-- colonyos-response -->",
        },
    }
    config_path = colonyos_dir / "config.yaml"
    import yaml
    config_path.write_text(yaml.safe_dump(config))

    # Create runs directory
    runs_dir = colonyos_dir / "runs"
    runs_dir.mkdir()

    # Initialize git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    return config_path


@pytest.fixture
def mock_pr_metadata():
    """Mock PR metadata response."""
    return {
        "headRefName": "colonyos/test-feature",
        "baseRefName": "main",
        "body": "Test PR description",
        "url": "https://github.com/test/repo/pull/42",
        "author": {"login": "testuser"},
    }


@pytest.fixture
def mock_comments():
    """Mock PR comments response."""
    return [
        {
            "id": 123456,
            "body": "Please extract this into a helper function",
            "path": "src/main.py",
            "line": 42,
            "original_line": 42,
            "user": {"login": "reviewer1", "type": "User"},
            "created_at": "2026-03-15T10:00:00Z",
        },
    ]


class TestPRRespondBasic:
    """Basic CLI invocation tests."""

    def test_requires_pr_number(self, runner: CliRunner) -> None:
        """Test that pr-respond requires a PR number argument."""
        result = runner.invoke(app, ["pr-respond"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "PR_REF" in result.output

    def test_invalid_pr_ref_format(self, runner: CliRunner, mock_config_file: Path, tmp_path: Path) -> None:
        """Test that invalid PR ref format shows an error."""
        with patch("colonyos.ci.validate_gh_auth"):
            result = runner.invoke(
                app, ["pr-respond", "invalid-ref"],
                catch_exceptions=False,
            )
        # Should fail because it can't parse the PR ref
        assert result.exit_code != 0


class TestPRRespondDryRun:
    """Tests for --dry-run flag."""

    def test_dry_run_shows_what_would_be_done(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path, mock_pr_metadata, mock_comments
    ) -> None:
        """Test that --dry-run shows comments without making changes."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            # Configure mock responses
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "pr" in cmd and "view" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_pr_metadata),
                        stderr="",
                    )
                elif "pulls" in str(cmd) and "comments" in str(cmd):
                    if "replies" in str(cmd):
                        return MagicMock(returncode=0, stdout="[]", stderr="")
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_comments),
                        stderr="",
                    )
                elif "collaborators" in str(cmd):
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            result = runner.invoke(
                app, ["pr-respond", "42", "--dry-run"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "DRY-RUN" in result.output
            assert "Would address" in result.output


class TestPRRespondCommentId:
    """Tests for --comment-id flag."""

    def test_comment_id_filters_to_specific_comment(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path, mock_pr_metadata
    ) -> None:
        """Test that --comment-id only processes the specified comment."""
        comments = [
            {
                "id": 111,
                "body": "First comment",
                "path": "src/a.py",
                "line": 10,
                "user": {"login": "reviewer1", "type": "User"},
                "created_at": "2026-03-15T10:00:00Z",
            },
            {
                "id": 222,
                "body": "Second comment",
                "path": "src/b.py",
                "line": 20,
                "user": {"login": "reviewer1", "type": "User"},
                "created_at": "2026-03-15T10:01:00Z",
            },
        ]

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "pr" in cmd and "view" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_pr_metadata),
                        stderr="",
                    )
                elif "pulls" in str(cmd) and "comments" in str(cmd):
                    if "replies" in str(cmd):
                        return MagicMock(returncode=0, stdout="[]", stderr="")
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(comments),
                        stderr="",
                    )
                elif "collaborators" in str(cmd):
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            result = runner.invoke(
                app, ["pr-respond", "42", "--comment-id", "111", "--dry-run"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "DRY-RUN" in result.output
            # Should only show the comment with ID 111
            assert "src/a.py" in result.output
            assert "src/b.py" not in result.output

    def test_comment_id_not_found_errors(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path, mock_pr_metadata, mock_comments
    ) -> None:
        """Test that --comment-id with invalid ID shows error."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "pr" in cmd and "view" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_pr_metadata),
                        stderr="",
                    )
                elif "pulls" in str(cmd) and "comments" in str(cmd):
                    if "replies" in str(cmd):
                        return MagicMock(returncode=0, stdout="[]", stderr="")
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_comments),
                        stderr="",
                    )
                elif "collaborators" in str(cmd):
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            result = runner.invoke(
                app, ["pr-respond", "42", "--comment-id", "999999"],
                catch_exceptions=False,
            )

            assert result.exit_code != 0
            assert "not found" in result.output.lower() or "already addressed" in result.output.lower()


class TestPRRespondBranchValidation:
    """Tests for branch prefix validation."""

    def test_non_colonyos_branch_errors(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path
    ) -> None:
        """Test that PR on non-colonyos branch shows error."""
        non_colonyos_pr_meta = {
            "headRefName": "feature/my-feature",  # Not a colonyos/ branch
            "baseRefName": "main",
            "body": "Test PR",
            "url": "https://github.com/test/repo/pull/42",
            "author": {"login": "testuser"},
        }

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(non_colonyos_pr_meta),
                stderr="",
            )

            result = runner.invoke(
                app, ["pr-respond", "42"],
                catch_exceptions=False,
            )

            assert result.exit_code != 0
            assert "does not use ColonyOS prefix" in result.output or "prefix" in result.output.lower()


class TestPRRespondRateLimiting:
    """Tests for rate limiting enforcement."""

    def test_rate_limit_exceeded_errors(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path, mock_pr_metadata, mock_comments
    ) -> None:
        """Test that exceeding rate limit shows error."""
        from datetime import datetime, timezone

        # Create a rate limit state file showing 3 responses this hour
        runs_dir = tmp_path / ".colonyos" / "runs"
        current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        state = {
            "pr_response_counts": {"42": {current_hour: 3}},  # Already at limit
            "aggregate_cost_usd": 0.0,
            "last_updated_iso": datetime.now(timezone.utc).isoformat(),
        }
        (runs_dir / "pr_respond_state.json").write_text(json.dumps(state))

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "pr" in cmd and "view" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_pr_metadata),
                        stderr="",
                    )
                elif "pulls" in str(cmd) and "comments" in str(cmd):
                    if "replies" in str(cmd):
                        return MagicMock(returncode=0, stdout="[]", stderr="")
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_comments),
                        stderr="",
                    )
                elif "collaborators" in str(cmd):
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            result = runner.invoke(
                app, ["pr-respond", "42"],
                catch_exceptions=False,
            )

            assert result.exit_code != 0
            assert "rate limit" in result.output.lower()


class TestPRRespondNoComments:
    """Tests for handling no comments case."""

    def test_no_comments_shows_message(
        self, runner: CliRunner, mock_config_file: Path, tmp_path: Path, mock_pr_metadata
    ) -> None:
        """Test that no comments shows appropriate message."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.ci.validate_gh_auth"), \
             patch("colonyos.ci.parse_pr_ref", return_value=42), \
             patch("colonyos.pr_comments.subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "pr" in cmd and "view" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps(mock_pr_metadata),
                        stderr="",
                    )
                elif "pulls" in str(cmd) and "comments" in str(cmd):
                    return MagicMock(returncode=0, stdout="[]", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            result = runner.invoke(
                app, ["pr-respond", "42"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "No review comments found" in result.output
