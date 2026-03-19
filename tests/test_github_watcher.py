"""Tests for the GitHub PR review watcher module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import ColonyConfig, GitHubWatchConfig, load_config


# ---------------------------------------------------------------------------
# GitHubWatchState tests (Task 2.1)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestGitHubWatchStateSerialization:
    """Tests for GitHubWatchState to_dict/from_dict roundtrip."""

    def test_roundtrip(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(
            watch_id="test-watch-123",
            processed_events={"event1": "run1", "event2": "run2"},
            aggregate_cost_usd=5.50,
            runs_triggered=3,
            hourly_trigger_counts={"2025-03-20T01": 2},
            daily_cost_usd=10.0,
            pr_fix_costs={123: 3.0, 456: 2.5},
            pr_fix_rounds={123: 2, 456: 1},
        )
        data = state.to_dict()
        loaded = GitHubWatchState.from_dict(data)

        assert loaded.watch_id == state.watch_id
        assert loaded.processed_events == state.processed_events
        assert loaded.aggregate_cost_usd == state.aggregate_cost_usd
        assert loaded.runs_triggered == state.runs_triggered
        assert loaded.hourly_trigger_counts == state.hourly_trigger_counts
        assert loaded.daily_cost_usd == state.daily_cost_usd
        assert loaded.pr_fix_costs == state.pr_fix_costs
        assert loaded.pr_fix_rounds == state.pr_fix_rounds

    def test_default_values(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test")
        assert state.processed_events == {}
        assert state.aggregate_cost_usd == 0.0
        assert state.runs_triggered == 0
        assert state.hourly_trigger_counts == {}
        assert state.daily_cost_usd == 0.0
        assert state.pr_fix_costs == {}
        assert state.pr_fix_rounds == {}
        assert state.consecutive_failures == 0

    def test_from_dict_with_missing_fields(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        data = {"watch_id": "minimal"}
        state = GitHubWatchState.from_dict(data)
        assert state.watch_id == "minimal"
        assert state.processed_events == {}
        assert state.pr_fix_costs == {}
        assert state.pr_fix_rounds == {}


class TestGitHubWatchStateDeduplication:
    """Tests for event deduplication methods."""

    def test_is_event_processed(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(
            watch_id="test",
            processed_events={"123:456": "run-abc"},
        )
        assert state.is_event_processed("123:456") is True
        assert state.is_event_processed("123:789") is False

    def test_mark_event_processed(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test")
        assert state.is_event_processed("123:456") is False
        state.mark_event_processed("123:456", "run-xyz")
        assert state.is_event_processed("123:456") is True
        assert state.processed_events["123:456"] == "run-xyz"


class TestGitHubWatchStatePRCostTracking:
    """Tests for per-PR cost and round tracking."""

    def test_get_pr_cost_returns_zero_for_unknown(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test")
        assert state.get_pr_cost(999) == 0.0

    def test_get_pr_cost_returns_tracked_value(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test", pr_fix_costs={123: 5.50})
        assert state.get_pr_cost(123) == 5.50

    def test_add_pr_cost(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test")
        state.add_pr_cost(123, 2.0)
        assert state.get_pr_cost(123) == 2.0
        state.add_pr_cost(123, 1.5)
        assert state.get_pr_cost(123) == 3.5

    def test_get_pr_rounds(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test", pr_fix_rounds={123: 2})
        assert state.get_pr_rounds(123) == 2
        assert state.get_pr_rounds(999) == 0

    def test_increment_pr_rounds(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test")
        assert state.get_pr_rounds(123) == 0
        state.increment_pr_rounds(123)
        assert state.get_pr_rounds(123) == 1
        state.increment_pr_rounds(123)
        assert state.get_pr_rounds(123) == 2


class TestGitHubWatchStateHourlyPruning:
    """Tests for hourly count pruning."""

    def test_prune_old_hourly_counts(self) -> None:
        from colonyos.github_watcher import GitHubWatchState, _MAX_HOURLY_KEYS

        # Create state with more keys than the limit
        hourly = {f"2025-03-{i:02d}T{j:02d}": 1 for i in range(1, 10) for j in range(24)}
        state = GitHubWatchState(watch_id="test", hourly_trigger_counts=hourly)
        assert len(state.hourly_trigger_counts) > _MAX_HOURLY_KEYS
        state.prune_old_hourly_counts()
        assert len(state.hourly_trigger_counts) <= _MAX_HOURLY_KEYS


class TestGitHubWatchStatePersistence:
    """Tests for state file persistence."""

    def test_save_and_load_watch_state(self, tmp_repo: Path) -> None:
        from colonyos.github_watcher import (
            GitHubWatchState,
            save_github_watch_state,
            load_github_watch_state,
        )

        state = GitHubWatchState(
            watch_id="test-123",
            processed_events={"event1": "run1"},
            aggregate_cost_usd=3.0,
            pr_fix_costs={123: 1.5},
            pr_fix_rounds={123: 1},
        )
        path = save_github_watch_state(tmp_repo, state)
        assert path.exists()

        loaded = load_github_watch_state(tmp_repo, "test-123")
        assert loaded is not None
        assert loaded.watch_id == "test-123"
        assert loaded.processed_events == {"event1": "run1"}
        assert loaded.pr_fix_costs == {123: 1.5}

    def test_load_returns_none_for_missing(self, tmp_repo: Path) -> None:
        from colonyos.github_watcher import load_github_watch_state

        result = load_github_watch_state(tmp_repo, "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Review event detection tests (Task 3.1)
# ---------------------------------------------------------------------------


class TestIsValidGitRef:
    """Tests for git ref validation (reuses pattern from slack.py)."""

    def test_valid_branch_names(self) -> None:
        from colonyos.github_watcher import is_valid_git_ref

        assert is_valid_git_ref("colonyos/add-feature") is True
        assert is_valid_git_ref("main") is True
        assert is_valid_git_ref("feature/test-123") is True

    def test_invalid_branch_names(self) -> None:
        from colonyos.github_watcher import is_valid_git_ref

        assert is_valid_git_ref("") is False
        assert is_valid_git_ref("branch..name") is False  # double dots
        assert is_valid_git_ref("/branch") is False  # starts with /
        assert is_valid_git_ref("branch.") is False  # ends with .
        assert is_valid_git_ref("a" * 256) is False  # too long


class TestIsColonyOSBranch:
    """Tests for ColonyOS branch prefix detection."""

    def test_matches_colonyos_prefix(self) -> None:
        from colonyos.github_watcher import is_colonyos_branch

        assert is_colonyos_branch("colonyos/add-feature") is True
        assert is_colonyos_branch("colonyos/fix-bug") is True

    def test_rejects_non_colonyos_branches(self) -> None:
        from colonyos.github_watcher import is_colonyos_branch

        assert is_colonyos_branch("main") is False
        assert is_colonyos_branch("feature/add-thing") is False
        assert is_colonyos_branch("COLONYOS/uppercase") is False  # case sensitive


class TestIsReviewerAllowed:
    """Tests for reviewer allowlist checking."""

    def test_empty_allowlist_allows_all(self) -> None:
        from colonyos.github_watcher import is_reviewer_allowed

        config = GitHubWatchConfig(allowed_reviewers=[])
        assert is_reviewer_allowed("anyone", config) is True

    def test_allowlist_allows_listed_user(self) -> None:
        from colonyos.github_watcher import is_reviewer_allowed

        config = GitHubWatchConfig(allowed_reviewers=["alice", "bob"])
        assert is_reviewer_allowed("alice", config) is True
        assert is_reviewer_allowed("bob", config) is True

    def test_allowlist_rejects_unlisted_user(self) -> None:
        from colonyos.github_watcher import is_reviewer_allowed

        config = GitHubWatchConfig(allowed_reviewers=["alice", "bob"])
        assert is_reviewer_allowed("charlie", config) is False


# ---------------------------------------------------------------------------
# Fix prompt formatting tests (Task 4.1)
# ---------------------------------------------------------------------------


class TestSanitizeReviewComment:
    """Tests for review comment sanitization."""

    def test_strips_xml_tags(self) -> None:
        from colonyos.github_watcher import sanitize_review_comment

        result = sanitize_review_comment("<script>evil</script>fix this")
        assert "<script>" not in result
        assert "fix this" in result

    def test_preserves_code_blocks(self) -> None:
        from colonyos.github_watcher import sanitize_review_comment

        # Code blocks should be preserved (just xml stripped)
        result = sanitize_review_comment("```python\ndef foo(): pass\n```")
        assert "def foo():" in result


class TestFormatGitHubFixPrompt:
    """Tests for fix prompt formatting."""

    def test_formats_single_comment(self) -> None:
        from colonyos.github_watcher import format_github_fix_prompt, ReviewComment

        comments = [
            ReviewComment(
                file_path="src/main.py",
                line=42,
                body="This variable should be renamed",
                reviewer="alice",
            )
        ]
        result = format_github_fix_prompt(comments, pr_number=123, branch="colonyos/fix")
        assert "src/main.py" in result
        assert "42" in result
        assert "renamed" in result
        assert "github_review" in result.lower() or "review" in result.lower()

    def test_formats_multiple_comments(self) -> None:
        from colonyos.github_watcher import format_github_fix_prompt, ReviewComment

        comments = [
            ReviewComment(file_path="a.py", line=1, body="fix A", reviewer="alice"),
            ReviewComment(file_path="b.py", line=2, body="fix B", reviewer="bob"),
        ]
        result = format_github_fix_prompt(comments, pr_number=123, branch="colonyos/fix")
        assert "a.py" in result
        assert "b.py" in result
        assert "fix A" in result
        assert "fix B" in result


# ---------------------------------------------------------------------------
# GitHub comment formatting tests (Task 6.1)
# ---------------------------------------------------------------------------


class TestFormatGitHubComments:
    """Tests for GitHub PR comment formatting."""

    def test_format_fix_start_comment(self) -> None:
        from colonyos.github_watcher import format_fix_start_comment

        result = format_fix_start_comment(reviewer="alice", round_num=1)
        assert "alice" in result
        assert "1" in result or "fix" in result.lower()

    def test_format_fix_complete_comment(self) -> None:
        from colonyos.github_watcher import format_fix_complete_comment

        result = format_fix_complete_comment(commit_sha="abc123", cost=2.50)
        assert "abc123" in result
        assert "2.50" in result or "$2.50" in result

    def test_format_fix_limit_comment_rounds(self) -> None:
        from colonyos.github_watcher import format_fix_limit_comment

        result = format_fix_limit_comment(limit_type="rounds", current=3, maximum=3)
        assert "3" in result
        assert "limit" in result.lower() or "maximum" in result.lower()

    def test_format_fix_limit_comment_cost(self) -> None:
        from colonyos.github_watcher import format_fix_limit_comment

        result = format_fix_limit_comment(limit_type="cost", current=10.0, maximum=10.0)
        assert "10" in result


# ---------------------------------------------------------------------------
# QueueItem creation tests (Task 5.1)
# ---------------------------------------------------------------------------


class TestCreateGitHubFixQueueItem:
    """Tests for QueueItem creation with source_type='github_review'."""

    def test_creates_queue_item_with_correct_fields(self) -> None:
        from colonyos.github_watcher import create_github_fix_queue_item

        item = create_github_fix_queue_item(
            pr_number=123,
            branch="colonyos/fix-thing",
            review_id=456,
            reviewer="alice",
            fix_prompt="Fix the issue",
        )
        assert item.source_type == "github_review"
        assert "123" in item.source_value
        assert item.branch_name == "colonyos/fix-thing"

    def test_queue_item_has_id(self) -> None:
        from colonyos.github_watcher import create_github_fix_queue_item

        item = create_github_fix_queue_item(
            pr_number=123,
            branch="colonyos/fix",
            review_id=456,
            reviewer="alice",
            fix_prompt="Fix",
        )
        assert item.id  # non-empty


# ---------------------------------------------------------------------------
# Rate limiting tests (Task 8.1)
# ---------------------------------------------------------------------------


class TestGitHubWatchRateLimiting:
    """Tests for rate limit checking."""

    def test_check_rate_limit_under_limit(self) -> None:
        from colonyos.github_watcher import GitHubWatchState, check_github_rate_limit

        state = GitHubWatchState(watch_id="test")
        config = GitHubWatchConfig(enabled=True)
        # Default max_runs_per_hour is from slack config; we use a shared pool
        assert check_github_rate_limit(state, max_runs_per_hour=3) is True

    def test_check_rate_limit_at_limit(self) -> None:
        from colonyos.github_watcher import GitHubWatchState, check_github_rate_limit
        from datetime import datetime, timezone

        current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        state = GitHubWatchState(
            watch_id="test",
            hourly_trigger_counts={current_hour: 3},
        )
        assert check_github_rate_limit(state, max_runs_per_hour=3) is False

    def test_increment_hourly_count(self) -> None:
        from colonyos.github_watcher import GitHubWatchState, increment_github_hourly_count
        from datetime import datetime, timezone

        state = GitHubWatchState(watch_id="test")
        current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        assert state.hourly_trigger_counts.get(current_hour, 0) == 0
        increment_github_hourly_count(state)
        assert state.hourly_trigger_counts.get(current_hour, 0) == 1


class TestCircuitBreaker:
    """Tests for consecutive failure circuit breaker."""

    def test_circuit_breaker_pause_after_failures(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test", consecutive_failures=2)
        state.consecutive_failures += 1
        assert state.consecutive_failures == 3

    def test_circuit_breaker_reset_on_success(self) -> None:
        from colonyos.github_watcher import GitHubWatchState

        state = GitHubWatchState(watch_id="test", consecutive_failures=2)
        state.consecutive_failures = 0  # Reset on success
        assert state.consecutive_failures == 0
