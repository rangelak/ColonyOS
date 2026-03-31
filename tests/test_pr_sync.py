"""Tests for the PR sync module."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from colonyos.config import ColonyConfig, DaemonConfig, PRSyncConfig
from colonyos.models import QueueItem, QueueItemStatus
from colonyos.outcomes import OutcomeStore


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_repo: Path) -> OutcomeStore:
    s = OutcomeStore(tmp_repo)
    yield s
    s.close()


def _make_config(
    *,
    enabled: bool = True,
    interval_minutes: int = 60,
    max_sync_failures: int = 3,
    branch_prefix: str = "colonyos/",
) -> ColonyConfig:
    """Build a ColonyConfig with the given pr_sync settings."""
    return ColonyConfig(
        branch_prefix=branch_prefix,
        daemon=DaemonConfig(
            pr_sync=PRSyncConfig(
                enabled=enabled,
                interval_minutes=interval_minutes,
                max_sync_failures=max_sync_failures,
            ),
        ),
    )


def _seed_pr(
    store: OutcomeStore,
    pr_number: int = 42,
    branch: str = "colonyos/feat-x",
    merge_state_status: str | None = None,
) -> None:
    """Insert a tracked open PR into the OutcomeStore."""
    store.track_pr(
        run_id="run-1",
        pr_number=pr_number,
        pr_url=f"https://github.com/test/repo/pull/{pr_number}",
        branch_name=branch,
    )
    if merge_state_status is not None:
        store.update_outcome(
            pr_number=pr_number,
            status="open",
            merge_state_status=merge_state_status,
        )


# ---------------------------------------------------------------------------
# TestPRSync
# ---------------------------------------------------------------------------


class TestPRSync:
    """Tests for sync_stale_prs() — the main entry point."""

    def test_skip_when_disabled(self, tmp_repo: Path, store: OutcomeStore):
        """Returns early if pr_sync.enabled is False."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=False)
        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    def test_write_enabled_gate(self, tmp_repo: Path, store: OutcomeStore):
        """Sync does nothing if write is not enabled."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="BEHIND")

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=False,
        )
        assert result is None

    def test_skip_non_colonyos_branches(self, tmp_repo: Path, store: OutcomeStore):
        """Filters out PRs not matching branch_prefix."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True, branch_prefix="colonyos/")
        _seed_pr(store, pr_number=99, branch="feature/not-colonyos", merge_state_status="BEHIND")

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    def test_skip_already_uptodate(self, tmp_repo: Path, store: OutcomeStore):
        """Skips PRs where mergeStateStatus is not BEHIND/DIRTY."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="CLEAN")

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    def test_skip_no_cached_merge_state(self, tmp_repo: Path, store: OutcomeStore):
        """Skips PRs with no cached mergeStateStatus."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        # Seed without merge_state_status
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    def test_max_failures_skips_pr(self, tmp_repo: Path, store: OutcomeStore):
        """PR with sync_failures >= max is not attempted."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True, max_sync_failures=3)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="BEHIND")
        # Set sync_failures to max
        store.update_sync_status(42, datetime.now(timezone.utc).isoformat(), 3)

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    def test_skip_branch_with_running_item(self, tmp_repo: Path, store: OutcomeStore):
        """Skips PR whose branch matches a RUNNING queue item."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="BEHIND")

        running_item = QueueItem(
            id="item-1",
            source_type="prompt",
            source_value="test",
            status=QueueItemStatus.RUNNING,
            branch_name="colonyos/feat-x",
        )

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[running_item],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )
        assert result is None

    @patch("colonyos.pr_sync._sync_single_pr")
    def test_clean_merge_success(
        self, mock_sync, tmp_repo: Path, store: OutcomeStore
    ):
        """Calls _sync_single_pr for BEHIND PRs with cached state."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="BEHIND")
        mock_sync.return_value = True  # success

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )

        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["pr_number"] == 42
        # Verify store is passed through (single connection)
        assert call_kwargs["store"] is not None

    @patch("colonyos.pr_sync._sync_single_pr")
    def test_dirty_state_triggers_sync(
        self, mock_sync, tmp_repo: Path, store: OutcomeStore
    ):
        """PRs with DIRTY mergeStateStatus are also sync candidates."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="DIRTY")
        mock_sync.return_value = False

        sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )

        mock_sync.assert_called_once()


class TestSyncSinglePR:
    """Tests for _sync_single_pr() — the per-PR merge logic."""

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_clean_merge_pushes_and_updates(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Clean merge pushes and resets sync_failures to 0."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        # Configure WorktreeManager mock
        mock_wt = MagicMock()
        mock_wt.create_detached_worktree.return_value = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt_cls.return_value = mock_wt

        # Mock subprocess calls
        mock_run.return_value = MagicMock(
            returncode=0, stdout="abc1234\n", stderr=""
        )

        result = _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=MagicMock(),
            store=store,
        )

        assert result is True
        # Verify WorktreeManager was used
        mock_wt.create_detached_worktree.assert_called_once()
        mock_wt.cleanup_worktree.assert_called_once_with("pr-sync-42")
        # Verify OutcomeStore was updated
        row = store.get_sync_candidates(10)
        assert len(row) == 1
        assert row[0]["sync_failures"] == 0
        assert row[0]["last_sync_at"] is not None

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_conflict_aborts_cleanly(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Merge conflict aborts, notifies Slack, comments on PR, increments failures."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
        slack_fn = MagicMock()

        # Configure WorktreeManager mock
        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            # Make 'git merge' fail
            if "merge" in cmd and "origin/main" in cmd and "--abort" not in cmd:
                result.returncode = 1
                result.stderr = "CONFLICT (content): Merge conflict in file.py\n"
                result.stdout = ""
            # Make 'git diff --name-only --diff-filter=U' return conflicting files
            if "diff" in cmd and "--diff-filter=U" in cmd:
                result.stdout = "file.py\n"
            return result

        mock_run.side_effect = side_effect

        result = _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=slack_fn,
            store=store,
        )

        assert result is False
        slack_fn.assert_called_once()
        mock_comment.assert_called_once()

        # Verify sync_failures incremented via direct query
        assert store.get_sync_failures(42) == 1

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_worktree_manager_lifecycle(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """WorktreeManager create and cleanup are called."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n", stderr="")

        _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=MagicMock(),
            store=store,
        )

        # Verify WorktreeManager was used for both create and cleanup
        mock_wt.create_detached_worktree.assert_called_once_with("pr-sync-42", "origin/colonyos/feat-x")
        mock_wt.cleanup_worktree.assert_called_once_with("pr-sync-42")

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_worktree_cleaned_on_failure(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """WorktreeManager cleanup is called even when merge fails."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if "merge" in cmd and "origin/main" in cmd and "--abort" not in cmd:
                result.returncode = 1
                result.stderr = "CONFLICT"
                result.stdout = ""
            if "diff" in cmd and "--diff-filter=U" in cmd:
                result.stdout = "file.py\n"
            return result

        mock_run.side_effect = side_effect

        _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=MagicMock(),
            store=store,
        )

        mock_wt.cleanup_worktree.assert_called_once_with("pr-sync-42")

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_escalation_at_max_failures(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """FR-10: Escalation notification when max_sync_failures reached."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
        # Set failures to max - 1 so next failure triggers escalation
        store.update_sync_status(42, datetime.now(timezone.utc).isoformat(), 2)
        slack_fn = MagicMock()

        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if "merge" in cmd and "origin/main" in cmd and "--abort" not in cmd:
                result.returncode = 1
                result.stderr = "CONFLICT"
                result.stdout = ""
            if "diff" in cmd and "--diff-filter=U" in cmd:
                result.stdout = "file.py\n"
            return result

        mock_run.side_effect = side_effect

        result = _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=slack_fn,
            store=store,
        )

        assert result is False
        # Should have 2 Slack calls: conflict notification + escalation
        assert slack_fn.call_count == 2
        escalation_msg = slack_fn.call_args_list[1][0][0]
        assert "maximum sync failure limit" in escalation_msg
        assert "rotating_light" in escalation_msg

        # Should have 2 PR comments: conflict + escalation
        assert mock_comment.call_count == 2
        escalation_comment = mock_comment.call_args_list[1][0][2]
        assert "Escalation" in escalation_comment
        assert "suspended" in escalation_comment

        # Verify failures count
        assert store.get_sync_failures(42) == 3

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_merge_has_timeout(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """The git merge subprocess call has a timeout."""
        from colonyos.pr_sync import _sync_single_pr, _MERGE_TIMEOUT_SECONDS

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n", stderr="")

        _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            max_sync_failures=3,
            post_slack_fn=MagicMock(),
            store=store,
        )

        # Find the merge call and verify it has timeout
        merge_calls = [
            c for c in mock_run.call_args_list
            if "merge" in (c[0][0] if c[0] else c[1].get("args", []))
            and "origin/main" in (c[0][0] if c[0] else c[1].get("args", []))
        ]
        assert len(merge_calls) >= 1
        merge_call = merge_calls[0]
        assert merge_call[1].get("timeout") == _MERGE_TIMEOUT_SECONDS


class TestGetSyncFailures:
    """Tests for OutcomeStore.get_sync_failures() — direct SQL query."""

    def test_returns_zero_for_unknown_pr(self, store: OutcomeStore):
        """Returns 0 for a PR not in the database."""
        assert store.get_sync_failures(999) == 0

    def test_returns_zero_for_new_pr(self, store: OutcomeStore):
        """Returns 0 for a freshly tracked PR."""
        _seed_pr(store, pr_number=42)
        assert store.get_sync_failures(42) == 0

    def test_returns_correct_failure_count(self, store: OutcomeStore):
        """Returns the exact failure count after update."""
        _seed_pr(store, pr_number=42)
        store.update_sync_status(42, datetime.now(timezone.utc).isoformat(), 5)
        assert store.get_sync_failures(42) == 5

    def test_reset_to_zero_after_success(self, store: OutcomeStore):
        """Returns 0 after failures are reset on successful sync."""
        _seed_pr(store, pr_number=42)
        store.update_sync_status(42, datetime.now(timezone.utc).isoformat(), 3)
        store.update_sync_status(42, datetime.now(timezone.utc).isoformat(), 0)
        assert store.get_sync_failures(42) == 0


class TestGetMergeStateStatus:
    """Tests for OutcomeStore.get_merge_state_status()."""

    def test_returns_none_for_unknown_pr(self, store: OutcomeStore):
        """Returns None for a PR not in the database."""
        assert store.get_merge_state_status(999) is None

    def test_returns_none_when_not_set(self, store: OutcomeStore):
        """Returns None for a PR that hasn't been polled yet."""
        _seed_pr(store, pr_number=42)
        assert store.get_merge_state_status(42) is None

    def test_returns_cached_state(self, store: OutcomeStore):
        """Returns the cached merge state after update_outcome."""
        _seed_pr(store, pr_number=42)
        store.update_outcome(pr_number=42, status="open", merge_state_status="BEHIND")
        assert store.get_merge_state_status(42) == "BEHIND"

    def test_updates_on_poll(self, store: OutcomeStore):
        """merge_state_status changes when updated."""
        _seed_pr(store, pr_number=42)
        store.update_outcome(pr_number=42, status="open", merge_state_status="BEHIND")
        store.update_outcome(pr_number=42, status="open", merge_state_status="CLEAN")
        assert store.get_merge_state_status(42) == "CLEAN"


# ---------------------------------------------------------------------------
# TestPRSyncIntegration
# ---------------------------------------------------------------------------


class TestPRSyncIntegration:
    """Integration-style test exercising the full sync flow end-to-end.

    Seeds an OutcomeStore with a tracked PR (including cached merge state),
    mocks git subprocess calls, and verifies that sync_stale_prs completes
    the full cycle: detect stale → fetch → worktree → merge → push → DB update.
    """

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_full_sync_success_flow(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Full flow: stale PR detected, merged, pushed, DB updated."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True, max_sync_failures=3)
        _seed_pr(store, pr_number=77, branch="colonyos/integration-test", merge_state_status="BEHIND")

        # Configure WorktreeManager mock
        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-77"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        # Build a subprocess side-effect that handles all git commands
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock(returncode=0, stdout="", stderr="")

            # git rev-parse → return a fake SHA
            if "rev-parse" in cmd:
                result.stdout = "abcdef1234567890abcdef1234567890abcdef12\n"
                return result

            # git merge origin/main --no-edit → success
            if "merge" in cmd and "origin/main" in cmd:
                result.returncode = 0
                return result

            # All other git commands (fetch, checkout, push) → success
            result.stdout = "ok\n"
            return result

        mock_run.side_effect = side_effect

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )

        # Sync should succeed
        assert result is True

        # Verify the database was updated: sync_failures reset to 0, last_sync_at set
        rows = store.get_sync_candidates(10)
        assert len(rows) == 1
        assert rows[0]["pr_number"] == 77
        assert rows[0]["sync_failures"] == 0
        assert rows[0]["last_sync_at"] is not None

        # No PR comment should be posted on success
        mock_comment.assert_not_called()

        # Verify WorktreeManager was used
        mock_wt.create_detached_worktree.assert_called_once()
        mock_wt.cleanup_worktree.assert_called_once()

        # Verify key git operations were called
        all_cmds = [c[0][0] for c in mock_run.call_args_list]

        # Should have fetched origin main
        fetch_main = [c for c in all_cmds if "fetch" in c and "main" in c]
        assert len(fetch_main) >= 1, "Expected git fetch origin main"

        # Should have pushed
        push_cmds = [c for c in all_cmds if "push" in c]
        assert len(push_cmds) >= 1, "Expected git push"

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_full_sync_conflict_flow(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Full flow: stale PR detected, merge conflicts, aborted, notified."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True, max_sync_failures=3)
        _seed_pr(store, pr_number=88, branch="colonyos/conflict-branch", merge_state_status="BEHIND")
        slack_fn = MagicMock()

        # Configure WorktreeManager mock
        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-88"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock(returncode=0, stdout="", stderr="")

            # git rev-parse
            if "rev-parse" in cmd:
                result.stdout = "abcdef1234567890\n"
                return result

            # git merge origin/main → conflict
            if "merge" in cmd and "origin/main" in cmd and "--abort" not in cmd:
                result.returncode = 1
                result.stderr = "CONFLICT (content): Merge conflict in api.py\n"
                result.stdout = ""
                return result

            # git diff --diff-filter=U → conflicting files
            if "diff" in cmd and "--diff-filter=U" in cmd:
                result.stdout = "api.py\nmodels.py\n"
                return result

            # Everything else succeeds
            result.stdout = "ok\n"
            return result

        mock_run.side_effect = side_effect

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=slack_fn,
            write_enabled=True,
        )

        # Sync should fail
        assert result is False

        # Slack notification was sent
        slack_fn.assert_called_once()
        slack_msg = slack_fn.call_args[0][0]
        assert "88" in slack_msg
        assert "conflict" in slack_msg.lower()

        # PR comment was posted
        mock_comment.assert_called_once()
        comment_args = mock_comment.call_args
        assert comment_args[0][1] == 88  # pr_number
        assert "api.py" in comment_args[0][2]  # body mentions conflicting file

        # Database updated with failure (via direct query)
        assert store.get_sync_failures(88) == 1

        # Worktree was cleaned up via WorktreeManager
        mock_wt.cleanup_worktree.assert_called_once()

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_full_flow_skips_uptodate_pr(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Full flow: PR is up-to-date (cached), no sync attempted."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=99, branch="colonyos/already-clean", merge_state_status="CLEAN")

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )

        assert result is None
        mock_comment.assert_not_called()
        # No subprocess calls should be made
        mock_run.assert_not_called()

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("colonyos.pr_sync.WorktreeManager")
    @patch("subprocess.run")
    def test_single_store_connection(
        self, mock_run, mock_wt_cls, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Verify only one OutcomeStore connection is used (no duplicate)."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True, max_sync_failures=3)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x", merge_state_status="BEHIND")

        mock_wt = MagicMock()
        wt_path = tmp_repo / ".colonyos" / "worktrees" / "task-pr-sync-42"
        mock_wt.create_detached_worktree.return_value = wt_path
        mock_wt_cls.return_value = mock_wt
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n", stderr="")

        # Patch OutcomeStore to count instantiations
        original_init = OutcomeStore.__init__
        init_count = [0]

        def counting_init(self_inner, *args, **kwargs):
            init_count[0] += 1
            return original_init(self_inner, *args, **kwargs)

        with patch.object(OutcomeStore, "__init__", counting_init):
            sync_stale_prs(
                repo_root=tmp_repo,
                config=config,
                queue_state_items=[],
                post_slack_fn=MagicMock(),
                write_enabled=True,
            )

        # Should create exactly 1 OutcomeStore instance (in sync_stale_prs)
        assert init_count[0] == 1, f"Expected 1 OutcomeStore, got {init_count[0]}"
