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


def _seed_pr(store: OutcomeStore, pr_number: int = 42, branch: str = "colonyos/feat-x") -> None:
    """Insert a tracked open PR into the OutcomeStore."""
    store.track_pr(
        run_id="run-1",
        pr_number=pr_number,
        pr_url=f"https://github.com/test/repo/pull/{pr_number}",
        branch_name=branch,
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
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

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
        _seed_pr(store, pr_number=99, branch="feature/not-colonyos")

        # Mock gh pr view to return BEHIND status
        gh_data = {"mergeStateStatus": "BEHIND"}
        with patch("colonyos.pr_sync._check_merge_state", return_value="BEHIND"):
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
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        with patch("colonyos.pr_sync._check_merge_state", return_value="CLEAN"):
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
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
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
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        running_item = QueueItem(
            id="item-1",
            source_type="prompt",
            source_value="test",
            status=QueueItemStatus.RUNNING,
            branch_name="colonyos/feat-x",
        )

        with patch("colonyos.pr_sync._check_merge_state", return_value="BEHIND"):
            result = sync_stale_prs(
                repo_root=tmp_repo,
                config=config,
                queue_state_items=[running_item],
                post_slack_fn=MagicMock(),
                write_enabled=True,
            )
        assert result is None

    @patch("colonyos.pr_sync._sync_single_pr")
    @patch("colonyos.pr_sync._check_merge_state", return_value="BEHIND")
    def test_clean_merge_success(
        self, mock_check, mock_sync, tmp_repo: Path, store: OutcomeStore
    ):
        """Mocks a clean merge, verifies _sync_single_pr is called."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
        mock_sync.return_value = True  # success

        result = sync_stale_prs(
            repo_root=tmp_repo,
            config=config,
            queue_state_items=[],
            post_slack_fn=MagicMock(),
            write_enabled=True,
        )

        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        assert call_kwargs[1]["pr_number"] == 42 or call_kwargs[0][1] == 42

    @patch("colonyos.pr_sync._sync_single_pr")
    @patch("colonyos.pr_sync._check_merge_state", return_value="DIRTY")
    def test_dirty_state_triggers_sync(
        self, mock_check, mock_sync, tmp_repo: Path, store: OutcomeStore
    ):
        """PRs with DIRTY mergeStateStatus are also sync candidates."""
        from colonyos.pr_sync import sync_stale_prs

        config = _make_config(enabled=True)
        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
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
    @patch("subprocess.run")
    def test_clean_merge_pushes_and_updates(
        self, mock_run, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Clean merge pushes and resets sync_failures to 0."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

        # Mock subprocess calls: fetch, worktree add, merge, rev-parse (pre), rev-parse (post), push, worktree remove
        mock_run.return_value = MagicMock(
            returncode=0, stdout="abc1234\n", stderr=""
        )

        result = _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            post_slack_fn=MagicMock(),
        )

        assert result is True
        # Verify OutcomeStore was updated
        row = store.get_sync_candidates(10)
        assert len(row) == 1
        assert row[0]["sync_failures"] == 0
        assert row[0]["last_sync_at"] is not None

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("subprocess.run")
    def test_conflict_aborts_cleanly(
        self, mock_run, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Merge conflict aborts, notifies Slack, comments on PR, increments failures."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
        slack_fn = MagicMock()

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
            post_slack_fn=slack_fn,
        )

        assert result is False
        slack_fn.assert_called_once()
        mock_comment.assert_called_once()

        # Verify sync_failures incremented
        rows = store.get_sync_candidates(10)
        assert len(rows) == 1
        assert rows[0]["sync_failures"] == 1

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("subprocess.run")
    def test_worktree_lifecycle(
        self, mock_run, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Worktree is created before merge and torn down after (success path)."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n", stderr="")

        _sync_single_pr(
            repo_root=tmp_repo,
            pr_number=42,
            branch_name="colonyos/feat-x",
            post_slack_fn=MagicMock(),
        )

        # Verify git worktree add and remove were called
        all_cmds = [c[0][0] for c in mock_run.call_args_list]
        worktree_add_calls = [c for c in all_cmds if "worktree" in c and "add" in c]
        worktree_remove_calls = [c for c in all_cmds if "worktree" in c and "remove" in c]
        assert len(worktree_add_calls) >= 1
        assert len(worktree_remove_calls) >= 1

    @patch("colonyos.pr_sync.post_pr_comment")
    @patch("subprocess.run")
    def test_worktree_cleaned_on_failure(
        self, mock_run, mock_comment, tmp_repo: Path, store: OutcomeStore
    ):
        """Worktree is torn down even when merge fails."""
        from colonyos.pr_sync import _sync_single_pr

        _seed_pr(store, pr_number=42, branch="colonyos/feat-x")

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
            post_slack_fn=MagicMock(),
        )

        all_cmds = [c[0][0] for c in mock_run.call_args_list]
        worktree_remove_calls = [c for c in all_cmds if "worktree" in c and "remove" in c]
        assert len(worktree_remove_calls) >= 1


class TestCheckMergeState:
    """Tests for _check_merge_state() helper."""

    @patch("subprocess.run")
    def test_returns_merge_state(self, mock_run, tmp_repo: Path):
        from colonyos.pr_sync import _check_merge_state

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"mergeStateStatus": "BEHIND"}',
            stderr="",
        )
        result = _check_merge_state(tmp_repo, 42)
        assert result == "BEHIND"

    @patch("subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run, tmp_repo: Path):
        from colonyos.pr_sync import _check_merge_state

        mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
        result = _check_merge_state(tmp_repo, 42)
        assert result == "UNKNOWN"

    @patch("subprocess.run")
    def test_returns_unknown_on_timeout(self, mock_run, tmp_repo: Path):
        from colonyos.pr_sync import _check_merge_state

        mock_run.side_effect = subprocess.TimeoutExpired("gh", 10)
        result = _check_merge_state(tmp_repo, 42)
        assert result == "UNKNOWN"
