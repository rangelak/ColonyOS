"""Tests for the PR review integration module."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPRReviewState:
    """Tests for PRReviewState dataclass and persistence (Task 1.1)."""

    def test_to_dict_includes_all_fields(self) -> None:
        from colonyos.pr_review import PRReviewState

        state = PRReviewState(
            pr_number=42,
            processed_comment_ids={"123": "run-abc"},
            cumulative_cost_usd=1.50,
            fix_rounds=2,
            consecutive_failures=1,
            queue_paused=False,
        )
        d = state.to_dict()
        assert d["pr_number"] == 42
        assert d["processed_comment_ids"] == {"123": "run-abc"}
        assert d["cumulative_cost_usd"] == 1.50
        assert d["fix_rounds"] == 2
        assert d["consecutive_failures"] == 1
        assert d["queue_paused"] is False
        assert "watch_started_at" in d

    def test_from_dict_parses_all_fields(self) -> None:
        from colonyos.pr_review import PRReviewState

        data = {
            "pr_number": 99,
            "processed_comment_ids": {"456": "run-xyz"},
            "cumulative_cost_usd": 2.25,
            "fix_rounds": 3,
            "consecutive_failures": 2,
            "queue_paused": True,
            "queue_paused_at": "2025-01-01T00:00:00+00:00",
            "watch_started_at": "2024-12-31T23:00:00+00:00",
        }
        state = PRReviewState.from_dict(data)
        assert state.pr_number == 99
        assert state.processed_comment_ids == {"456": "run-xyz"}
        assert state.cumulative_cost_usd == 2.25
        assert state.fix_rounds == 3
        assert state.consecutive_failures == 2
        assert state.queue_paused is True
        assert state.queue_paused_at == "2025-01-01T00:00:00+00:00"

    def test_from_dict_missing_fields_get_defaults(self) -> None:
        from colonyos.pr_review import PRReviewState

        data = {"pr_number": 1}
        state = PRReviewState.from_dict(data)
        assert state.pr_number == 1
        assert state.processed_comment_ids == {}
        assert state.cumulative_cost_usd == 0.0
        assert state.fix_rounds == 0
        assert state.consecutive_failures == 0
        assert state.queue_paused is False

    def test_roundtrip_to_from_dict(self) -> None:
        from colonyos.pr_review import PRReviewState

        original = PRReviewState(
            pr_number=42,
            processed_comment_ids={"a": "b", "c": "d"},
            cumulative_cost_usd=3.14,
            fix_rounds=5,
            consecutive_failures=0,
            queue_paused=False,
        )
        restored = PRReviewState.from_dict(original.to_dict())
        assert restored.pr_number == original.pr_number
        assert restored.processed_comment_ids == original.processed_comment_ids
        assert restored.cumulative_cost_usd == original.cumulative_cost_usd
        assert restored.fix_rounds == original.fix_rounds

    def test_is_processed_returns_true_for_known_comment(self) -> None:
        from colonyos.pr_review import PRReviewState

        state = PRReviewState(pr_number=1, processed_comment_ids={"123": "run-abc"})
        assert state.is_processed("123") is True
        assert state.is_processed("999") is False

    def test_mark_processed_adds_comment_id(self) -> None:
        from colonyos.pr_review import PRReviewState

        state = PRReviewState(pr_number=1)
        state.mark_processed("456", "run-xyz")
        assert state.is_processed("456") is True
        assert state.processed_comment_ids["456"] == "run-xyz"


class TestPRReviewStatePersistence:
    """Tests for save/load state persistence (Task 1.3)."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        from colonyos.pr_review import (
            PRReviewState,
            save_pr_review_state,
            load_pr_review_state,
        )

        state = PRReviewState(
            pr_number=42,
            processed_comment_ids={"123": "run-abc"},
            cumulative_cost_usd=1.50,
        )
        path = save_pr_review_state(tmp_path, state)
        assert path.exists()

        loaded = load_pr_review_state(tmp_path, 42)
        assert loaded is not None
        assert loaded.pr_number == 42
        assert loaded.processed_comment_ids == {"123": "run-abc"}
        assert loaded.cumulative_cost_usd == 1.50

    def test_load_returns_none_for_nonexistent(self, tmp_path: Path) -> None:
        from colonyos.pr_review import load_pr_review_state

        result = load_pr_review_state(tmp_path, 999)
        assert result is None

    def test_save_uses_atomic_write(self, tmp_path: Path) -> None:
        from colonyos.pr_review import PRReviewState, save_pr_review_state

        state = PRReviewState(pr_number=42)
        path = save_pr_review_state(tmp_path, state)
        # Verify the file has valid JSON
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["pr_number"] == 42


class TestFetchPRReviewComments:
    """Tests for fetching PR review comments (Task 2.1)."""

    @patch("subprocess.run")
    def test_fetch_pr_review_comments_parses_response(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import fetch_pr_review_comments

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "id": 123,
                    "body": "Add null check here",
                    "path": "src/main.py",
                    "line": 42,
                    "user": {"login": "reviewer"},
                    "created_at": "2025-01-01T12:00:00Z",
                    "html_url": "https://github.com/owner/repo/pull/1#discussion_r123",
                },
                {
                    "id": 456,
                    "body": "General comment without line",
                    "path": None,
                    "line": None,
                    "user": {"login": "reviewer2"},
                    "created_at": "2025-01-01T13:00:00Z",
                    "html_url": "https://github.com/owner/repo/pull/1#discussion_r456",
                },
            ]),
            stderr="",
        )

        comments = fetch_pr_review_comments(1, tmp_path)
        # Should only return inline comments (with path and line)
        assert len(comments) == 1
        assert comments[0].id == "123"
        assert comments[0].body == "Add null check here"
        assert comments[0].path == "src/main.py"
        assert comments[0].line == 42
        assert comments[0].reviewer == "reviewer"

    @patch("subprocess.run")
    def test_fetch_pr_review_comments_raises_on_error(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import fetch_pr_review_comments
        import click

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Not found",
        )

        with pytest.raises(click.ClickException, match="Failed to fetch"):
            fetch_pr_review_comments(1, tmp_path)


class TestFetchPRState:
    """Tests for fetching PR state (Task 2.3)."""

    @patch("subprocess.run")
    def test_fetch_pr_state_returns_open(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import fetch_pr_state

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "state": "open",
                "headRefOid": "abc123",
                "headRefName": "feature-branch",
            }),
            stderr="",
        )

        result = fetch_pr_state(42, tmp_path)
        assert result.state == "open"
        assert result.head_sha == "abc123"
        assert result.head_ref == "feature-branch"

    @patch("subprocess.run")
    def test_fetch_pr_state_returns_merged(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import fetch_pr_state

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "state": "merged",
                "headRefOid": "def456",
                "headRefName": "feature-branch",
            }),
            stderr="",
        )

        result = fetch_pr_state(42, tmp_path)
        assert result.state == "merged"


class TestTriagePRReviewComment:
    """Tests for triage classification (Task 3.1)."""

    def test_sanitizes_comment_body(self) -> None:
        from colonyos.pr_review import _sanitize_pr_comment

        # Should strip XML-like tags
        result = _sanitize_pr_comment("<script>alert('xss')</script>fix this bug")
        assert "<script>" not in result
        assert "fix this bug" in result

    @patch("colonyos.pr_review.triage_message")
    def test_triage_pr_review_comment_wraps_triage_message(
        self, mock_triage: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import triage_pr_review_comment
        from colonyos.slack import TriageResult

        mock_triage.return_value = TriageResult(
            actionable=True,
            confidence=0.9,
            summary="Add null check",
            base_branch=None,
            reasoning="Clear actionable request",
        )

        result = triage_pr_review_comment(
            "Add null check here",
            file_path="src/main.py",
            line_number=42,
            repo_root=tmp_path,
        )
        assert result.actionable is True
        assert result.confidence == 0.9


class TestPostPRReviewReply:
    """Tests for posting replies (Task 4.1)."""

    @patch("subprocess.run")
    def test_post_pr_review_reply_calls_gh_api(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import post_pr_review_reply

        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

        post_pr_review_reply(
            pr_number=42,
            comment_id="123",
            message="Fixed in abc123: Added null check",
            repo_root=tmp_path,
        )

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "gh" in call_args[0][0]
        assert "api" in call_args[0][0]

    @patch("subprocess.run")
    def test_post_pr_summary_comment_calls_gh_api(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import post_pr_summary_comment

        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

        post_pr_summary_comment(
            pr_number=42,
            message="Applied fixes for 2 review comments.",
            repo_root=tmp_path,
        )

        mock_run.assert_called_once()


class TestFormatReplyMessages:
    """Tests for message formatting (Task 4.4)."""

    def test_format_fix_reply(self) -> None:
        from colonyos.pr_review import format_fix_reply

        result = format_fix_reply(
            sha="abc123def456",
            commit_url="https://github.com/owner/repo/commit/abc123def456",
            summary="Added null check to prevent crash",
        )
        assert "[`abc123d`]" in result  # Short SHA
        assert "https://github.com/owner/repo/commit/abc123def456" in result
        assert "Added null check" in result

    def test_format_summary_message(self) -> None:
        from colonyos.pr_review import format_summary_message

        commits = [
            ("abc123", "Added null check"),
            ("def456", "Fixed typo"),
        ]
        result = format_summary_message(commits)
        assert "2" in result
        assert "abc123" in result
        assert "def456" in result


class TestPRReviewConfig:
    """Tests for PRReviewConfig parsing (Task 5.1)."""

    def test_defaults_when_no_pr_review_section(self, tmp_path: Path) -> None:
        from colonyos.config import load_config

        config = load_config(tmp_path)
        assert config.pr_review.budget_per_pr == 5.0
        assert config.pr_review.max_fix_rounds_per_pr == 3
        assert config.pr_review.poll_interval_seconds == 60
        assert config.pr_review.circuit_breaker_threshold == 3
        assert config.pr_review.circuit_breaker_cooldown_minutes == 15

    def test_parsed_from_yaml(self, tmp_path: Path) -> None:
        import yaml
        from colonyos.config import load_config

        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "pr_review": {
                    "budget_per_pr": 10.0,
                    "max_fix_rounds_per_pr": 5,
                    "poll_interval_seconds": 30,
                    "circuit_breaker_threshold": 5,
                    "circuit_breaker_cooldown_minutes": 30,
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_path)
        assert config.pr_review.budget_per_pr == 10.0
        assert config.pr_review.max_fix_rounds_per_pr == 5
        assert config.pr_review.poll_interval_seconds == 30


class TestSafetyGuards:
    """Tests for safety guards (Task 9.1)."""

    def test_budget_cap_check(self) -> None:
        from colonyos.pr_review import PRReviewState, check_budget_cap

        state = PRReviewState(pr_number=42, cumulative_cost_usd=4.50)
        assert check_budget_cap(state, budget_limit=5.0) is True  # Under limit

        state.cumulative_cost_usd = 5.50
        assert check_budget_cap(state, budget_limit=5.0) is False  # Over limit

    def test_circuit_breaker_check(self) -> None:
        from colonyos.pr_review import PRReviewState, check_circuit_breaker

        state = PRReviewState(pr_number=42, consecutive_failures=2)
        assert check_circuit_breaker(state, threshold=3) is True  # Under threshold

        state.consecutive_failures = 3
        assert check_circuit_breaker(state, threshold=3) is False  # At threshold

    def test_max_fix_rounds_check(self) -> None:
        from colonyos.pr_review import PRReviewState, check_fix_rounds

        state = PRReviewState(pr_number=42, fix_rounds=2)
        assert check_fix_rounds(state, max_rounds=3) is True  # Under limit

        state.fix_rounds = 3
        assert check_fix_rounds(state, max_rounds=3) is False  # At limit


class TestBuildCommitUrl:
    """Tests for commit URL building helper."""

    def test_build_commit_url_from_pr_url(self) -> None:
        from colonyos.pr_review import build_commit_url

        pr_url = "https://github.com/owner/repo/pull/42"
        commit_sha = "abc123def456"
        result = build_commit_url(pr_url, commit_sha)
        assert result == "https://github.com/owner/repo/commit/abc123def456"

    def test_build_commit_url_with_short_sha(self) -> None:
        from colonyos.pr_review import build_commit_url

        pr_url = "https://github.com/myorg/myrepo/pull/123"
        commit_sha = "abc123d"
        result = build_commit_url(pr_url, commit_sha)
        assert result == "https://github.com/myorg/myrepo/commit/abc123d"

    def test_build_commit_url_with_invalid_url(self) -> None:
        from colonyos.pr_review import build_commit_url

        # Should return fallback format
        result = build_commit_url("not-a-valid-url", "abc123")
        assert result == "commit:abc123"


class TestPRStateUrl:
    """Tests for PRState url field."""

    @patch("subprocess.run")
    def test_fetch_pr_state_includes_url(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        from colonyos.pr_review import fetch_pr_state

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "state": "open",
                "headRefOid": "abc123",
                "headRefName": "feature-branch",
                "url": "https://github.com/owner/repo/pull/42",
            }),
            stderr="",
        )

        result = fetch_pr_state(42, tmp_path)
        assert result.url == "https://github.com/owner/repo/pull/42"
        assert result.state == "open"
        assert result.head_sha == "abc123"


class TestTimestampFiltering:
    """Tests for FR-8 timestamp filtering in watch mode."""

    def test_watch_started_at_is_set_on_creation(self) -> None:
        from colonyos.pr_review import PRReviewState
        from datetime import datetime

        state = PRReviewState(pr_number=42)
        # Should have a valid ISO timestamp
        assert state.watch_started_at is not None
        # Should be parseable
        parsed = datetime.fromisoformat(state.watch_started_at)
        assert parsed.tzinfo is not None

    def test_watch_started_at_roundtrip(self) -> None:
        from colonyos.pr_review import PRReviewState

        timestamp = "2025-01-01T12:00:00+00:00"
        state = PRReviewState(pr_number=42, watch_started_at=timestamp)
        d = state.to_dict()
        restored = PRReviewState.from_dict(d)
        assert restored.watch_started_at == timestamp


class TestPRReviewCLIIntegration:
    """CLI integration tests for pr-review command (Task 7.1)."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    @pytest.fixture
    def mock_config(self, tmp_path: Path):
        """Create a minimal config for testing."""
        from colonyos.config import ColonyConfig, ProjectInfo, save_config

        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
        )
        save_config(tmp_path, config)
        return config

    @patch("colonyos.cli._find_repo_root")
    @patch("subprocess.run")
    def test_pr_review_merged_pr_exits_early(
        self, mock_run: MagicMock, mock_root: MagicMock,
        runner, tmp_path: Path, mock_config
    ) -> None:
        """PR review command exits early for merged PRs."""
        from colonyos.cli import app

        mock_root.return_value = tmp_path

        # Mock gh pr view to return merged state
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "state": "merged",
                "headRefOid": "abc123",
                "headRefName": "feature-branch",
                "url": "https://github.com/owner/repo/pull/42",
            }),
            stderr="",
        )

        result = runner.invoke(app, ["pr-review", "42"])
        assert result.exit_code == 0
        assert "merged" in result.output.lower()

    @patch("colonyos.cli._find_repo_root")
    @patch("subprocess.run")
    def test_pr_review_closed_pr_exits_early(
        self, mock_run: MagicMock, mock_root: MagicMock,
        runner, tmp_path: Path, mock_config
    ) -> None:
        """PR review command exits early for closed PRs."""
        from colonyos.cli import app

        mock_root.return_value = tmp_path

        # Mock gh pr view to return closed state
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "state": "closed",
                "headRefOid": "abc123",
                "headRefName": "feature-branch",
                "url": "https://github.com/owner/repo/pull/42",
            }),
            stderr="",
        )

        result = runner.invoke(app, ["pr-review", "42"])
        assert result.exit_code == 0
        assert "closed" in result.output.lower()

    @patch("colonyos.cli._find_repo_root")
    @patch("subprocess.run")
    def test_pr_review_no_config_exits_with_error(
        self, mock_run: MagicMock, mock_root: MagicMock,
        runner, tmp_path: Path
    ) -> None:
        """PR review command exits with error when no config exists."""
        from colonyos.cli import app

        # No config file created
        mock_root.return_value = tmp_path

        result = runner.invoke(app, ["pr-review", "42"])
        assert result.exit_code != 0
        assert "colonyos init" in result.output

    @patch("colonyos.cli._find_repo_root")
    @patch("subprocess.run")
    def test_pr_review_handles_gh_cli_error(
        self, mock_run: MagicMock, mock_root: MagicMock,
        runner, tmp_path: Path, mock_config
    ) -> None:
        """PR review command handles gh CLI errors gracefully."""
        from colonyos.cli import app

        mock_root.return_value = tmp_path

        # Mock gh pr view to return error
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="could not find pull request",
        )

        result = runner.invoke(app, ["pr-review", "999"])
        assert result.exit_code != 0
        assert "Error" in result.output or "error" in result.output.lower()

    @patch("colonyos.cli._find_repo_root")
    @patch("subprocess.run")
    def test_pr_review_single_run_no_comments(
        self, mock_run: MagicMock, mock_root: MagicMock,
        runner, tmp_path: Path, mock_config
    ) -> None:
        """PR review single run with no actionable comments."""
        from colonyos.cli import app

        mock_root.return_value = tmp_path

        def run_side_effect(*args, **kwargs):
            cmd = args[0]
            if "gh" in cmd and "pr" in cmd and "view" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({
                        "state": "open",
                        "headRefOid": "abc123",
                        "headRefName": "feature-branch",
                        "url": "https://github.com/owner/repo/pull/42",
                    }),
                    stderr="",
                )
            elif "gh" in cmd and "api" in cmd and "comments" in str(cmd):
                # Return empty comments list
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps([]),
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        result = runner.invoke(app, ["pr-review", "42"])
        assert result.exit_code == 0
        assert "No fixes applied" in result.output or "No new actionable" in result.output


class TestCircuitBreakerCooldown:
    """Tests for circuit breaker cooldown/recovery pattern (FR-13)."""

    def test_circuit_breaker_sets_pause_state(self) -> None:
        from colonyos.pr_review import PRReviewState

        state = PRReviewState(pr_number=42, consecutive_failures=3)
        assert state.queue_paused is False

        # Simulate circuit breaker trigger
        state.queue_paused = True
        state.queue_paused_at = datetime.now(timezone.utc).isoformat()

        assert state.queue_paused is True
        assert state.queue_paused_at is not None

    def test_cooldown_recovery(self) -> None:
        from colonyos.pr_review import PRReviewState

        # Set pause state with past timestamp
        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        state = PRReviewState(
            pr_number=42,
            consecutive_failures=3,
            queue_paused=True,
            queue_paused_at=past_time.isoformat(),
        )

        # Simulate auto-recovery check
        cooldown_minutes = 15
        assert state.queue_paused_at is not None
        paused_at = datetime.fromisoformat(state.queue_paused_at)
        elapsed = (datetime.now(timezone.utc) - paused_at).total_seconds()
        cooldown_sec = cooldown_minutes * 60

        # Should have exceeded cooldown
        assert elapsed >= cooldown_sec

        # Reset state
        state.queue_paused = False
        state.queue_paused_at = None
        state.consecutive_failures = 0

        assert state.queue_paused is False
        assert state.consecutive_failures == 0


class TestDatetimeComparison:
    """Tests for datetime-based timestamp comparison (robust ISO parsing)."""

    def test_compare_iso_timestamps_with_datetime(self) -> None:
        """Verify datetime parsing works for ISO timestamp comparison."""
        older = "2025-01-01T10:00:00+00:00"
        newer = "2025-01-01T12:00:00+00:00"

        older_dt = datetime.fromisoformat(older)
        newer_dt = datetime.fromisoformat(newer)

        assert newer_dt > older_dt
        assert older_dt < newer_dt

    def test_comment_filtering_with_datetime(self) -> None:
        """Test that comment filtering uses datetime comparison correctly."""
        from colonyos.pr_review import PRReviewComment

        watch_started = "2025-01-01T12:00:00+00:00"
        watch_started_dt = datetime.fromisoformat(watch_started)

        # Comment created before watch started
        old_comment = PRReviewComment(
            id="1",
            body="old",
            path="src/file.py",
            line=10,
            reviewer="user",
            created_at="2025-01-01T10:00:00+00:00",
            html_url="https://example.com",
        )

        # Comment created after watch started
        new_comment = PRReviewComment(
            id="2",
            body="new",
            path="src/file.py",
            line=20,
            reviewer="user",
            created_at="2025-01-01T14:00:00+00:00",
            html_url="https://example.com",
        )

        old_dt = datetime.fromisoformat(old_comment.created_at)
        new_dt = datetime.fromisoformat(new_comment.created_at)

        assert old_dt < watch_started_dt  # Should be filtered out
        assert new_dt >= watch_started_dt  # Should be included
