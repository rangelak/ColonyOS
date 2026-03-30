"""Tests for the PR outcome tracking module."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.outcomes import (
    OutcomeStore,
    poll_outcomes,
    compute_outcome_stats,
    format_outcome_summary,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def store(tmp_repo: Path) -> OutcomeStore:
    s = OutcomeStore(tmp_repo)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1.1 OutcomeStore class tests
# ---------------------------------------------------------------------------


class TestOutcomeStoreInit:
    def test_creates_table(self, tmp_repo: Path):
        """OutcomeStore creates pr_outcomes table on init."""
        s = OutcomeStore(tmp_repo)
        # Verify table exists by querying it
        cur = s._conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pr_outcomes'")
        assert cur.fetchone() is not None
        s.close()

    def test_idempotent_init(self, tmp_repo: Path):
        """Opening the store twice should not error (schema migration)."""
        s1 = OutcomeStore(tmp_repo)
        s1.close()
        s2 = OutcomeStore(tmp_repo)
        s2.close()

    def test_shares_memory_db(self, tmp_repo: Path):
        """OutcomeStore uses the same memory.db as MemoryStore."""
        s = OutcomeStore(tmp_repo)
        assert s._db_path == tmp_repo / ".colonyos" / "memory.db"
        s.close()

    def test_context_manager(self, tmp_repo: Path):
        """OutcomeStore supports with-statement."""
        with OutcomeStore(tmp_repo) as s:
            s.track_pr("run-1", 42, "https://github.com/o/r/pull/42", "feat/x")
            assert len(s.get_outcomes()) == 1


class TestTrackPr:
    def test_persists_record(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "https://github.com/o/r/pull/42", "feat/x")
        outcomes = store.get_outcomes()
        assert len(outcomes) == 1
        row = outcomes[0]
        assert row["run_id"] == "run-1"
        assert row["pr_number"] == 42
        assert row["pr_url"] == "https://github.com/o/r/pull/42"
        assert row["branch_name"] == "feat/x"
        assert row["status"] == "open"
        assert row["created_at"] is not None
        assert row["merged_at"] is None
        assert row["closed_at"] is None

    def test_multiple_prs(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "https://github.com/o/r/pull/42", "feat/x")
        store.track_pr("run-2", 43, "https://github.com/o/r/pull/43", "feat/y")
        assert len(store.get_outcomes()) == 2


class TestGetOutcomes:
    def test_returns_all_records(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "url1", "b1")
        store.track_pr("run-2", 43, "url2", "b2")
        outcomes = store.get_outcomes()
        assert len(outcomes) == 2

    def test_empty_table(self, store: OutcomeStore):
        assert store.get_outcomes() == []


class TestGetOpenOutcomes:
    def test_returns_only_open(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "url1", "b1")
        store.track_pr("run-2", 43, "url2", "b2")
        # Manually close one
        store._conn.execute(
            "UPDATE pr_outcomes SET status = 'merged' WHERE pr_number = 42"
        )
        store._conn.commit()
        open_outcomes = store.get_open_outcomes()
        assert len(open_outcomes) == 1
        assert open_outcomes[0]["pr_number"] == 43


class TestUpdateOutcome:
    def test_update_status_merged(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "url1", "b1")
        now = datetime.now(timezone.utc).isoformat()
        store.update_outcome(
            pr_number=42,
            status="merged",
            merged_at=now,
            review_comment_count=3,
            ci_passed=True,
            labels="bug,fix",
        )
        outcomes = store.get_outcomes()
        assert outcomes[0]["status"] == "merged"
        assert outcomes[0]["merged_at"] == now
        assert outcomes[0]["review_comment_count"] == 3
        assert outcomes[0]["ci_passed"] == 1  # SQLite stores bool as int
        assert outcomes[0]["labels"] == "bug,fix"

    def test_update_status_closed_with_context(self, store: OutcomeStore):
        store.track_pr("run-1", 42, "url1", "b1")
        now = datetime.now(timezone.utc).isoformat()
        store.update_outcome(
            pr_number=42,
            status="closed",
            closed_at=now,
            close_context="Too large, please split",
        )
        outcomes = store.get_outcomes()
        assert outcomes[0]["status"] == "closed"
        assert outcomes[0]["closed_at"] == now
        assert outcomes[0]["close_context"] == "Too large, please split"


# ---------------------------------------------------------------------------
# 1.2 poll_outcomes() tests
# ---------------------------------------------------------------------------


def _make_gh_result(
    state: str = "OPEN",
    merged_at: str | None = None,
    closed_at: str | None = None,
    reviews: list | None = None,
    comments: list | None = None,
    status_checks: list | None = None,
    labels: list | None = None,
) -> dict:
    """Build a dict matching `gh pr view --json` output."""
    return {
        "state": state,
        "mergedAt": merged_at,
        "closedAt": closed_at,
        "reviews": reviews or [],
        "comments": comments or [],
        "statusCheckRollup": status_checks or [],
        "labels": labels or [],
    }


class TestPollOutcomes:
    def test_open_to_merged(self, store: OutcomeStore, tmp_repo: Path):
        store.track_pr("run-1", 42, "url1", "b1")
        gh_data = _make_gh_result(
            state="MERGED",
            merged_at="2025-01-15T10:00:00Z",
            reviews=[{"body": "LGTM"}, {"body": "Nice work"}],
            status_checks=[{"conclusion": "SUCCESS"}],
            labels=[{"name": "bugfix"}],
        )
        with patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data):
            poll_outcomes(tmp_repo)
        outcomes = store.get_outcomes()
        assert outcomes[0]["status"] == "merged"
        assert outcomes[0]["merged_at"] == "2025-01-15T10:00:00Z"
        assert outcomes[0]["review_comment_count"] == 2
        assert outcomes[0]["ci_passed"] == 1
        assert outcomes[0]["labels"] == "bugfix"

    def test_open_to_closed_with_context(self, store: OutcomeStore, tmp_repo: Path):
        store.track_pr("run-1", 42, "url1", "b1")
        gh_data = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            comments=[{"body": "This PR is too large, please split into smaller PRs."}],
        )
        with patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data):
            poll_outcomes(tmp_repo)
        outcomes = store.get_outcomes()
        assert outcomes[0]["status"] == "closed"
        assert "too large" in outcomes[0]["close_context"].lower()

    def test_close_context_sanitized(self, store: OutcomeStore, tmp_repo: Path):
        """close_context is sanitized with sanitize_ci_logs."""
        store.track_pr("run-1", 42, "url1", "b1")
        gh_data = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            comments=[{"body": "Bad token: ghp_abc123def456 found in code"}],
        )
        with patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data):
            poll_outcomes(tmp_repo)
        outcomes = store.get_outcomes()
        # Secret should be redacted
        assert "ghp_" not in outcomes[0]["close_context"]
        assert "[REDACTED]" in outcomes[0]["close_context"]

    def test_close_context_capped_at_500_chars(self, store: OutcomeStore, tmp_repo: Path):
        store.track_pr("run-1", 42, "url1", "b1")
        long_comment = "x" * 1000
        gh_data = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            comments=[{"body": long_comment}],
        )
        with patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data):
            poll_outcomes(tmp_repo)
        outcomes = store.get_outcomes()
        assert len(outcomes[0]["close_context"]) <= 500

    def test_gh_cli_failure_logs_and_continues(self, store: OutcomeStore, tmp_repo: Path):
        store.track_pr("run-1", 42, "url1", "b1")
        store.track_pr("run-2", 43, "url2", "b2")
        call_count = 0

        def mock_gh(pr_number, repo_root):
            nonlocal call_count
            call_count += 1
            if pr_number == 42:
                raise subprocess.CalledProcessError(1, "gh")
            return _make_gh_result(
                state="MERGED",
                merged_at="2025-01-15T10:00:00Z",
            )

        with patch("colonyos.outcomes._call_gh_pr_view", side_effect=mock_gh):
            poll_outcomes(tmp_repo)  # Should not raise

        outcomes = store.get_outcomes()
        # PR 42 should still be open (gh failed), PR 43 should be merged
        pr42 = [o for o in outcomes if o["pr_number"] == 42][0]
        pr43 = [o for o in outcomes if o["pr_number"] == 43][0]
        assert pr42["status"] == "open"
        assert pr43["status"] == "merged"

    def test_skips_already_resolved(self, store: OutcomeStore, tmp_repo: Path):
        """Already merged/closed PRs should not be polled."""
        store.track_pr("run-1", 42, "url1", "b1")
        store._conn.execute(
            "UPDATE pr_outcomes SET status = 'merged' WHERE pr_number = 42"
        )
        store._conn.commit()

        with patch("colonyos.outcomes._call_gh_pr_view") as mock_gh:
            poll_outcomes(tmp_repo)
            mock_gh.assert_not_called()


# ---------------------------------------------------------------------------
# 1.3 compute_outcome_stats() tests
# ---------------------------------------------------------------------------


class TestComputeOutcomeStats:
    def test_empty_outcomes(self, tmp_repo: Path):
        stats = compute_outcome_stats(tmp_repo)
        assert stats["total_tracked"] == 0
        assert stats["merge_rate"] == 0.0
        assert stats["avg_time_to_merge_hours"] == 0.0

    def test_merge_rate(self, store: OutcomeStore, tmp_repo: Path):
        # 2 merged, 1 closed, 1 open = merge rate = 2/3 (exclude open)
        for i, (status, merged_at, closed_at) in enumerate([
            ("merged", "2025-01-15T12:00:00Z", None),
            ("merged", "2025-01-15T14:00:00Z", None),
            ("closed", None, "2025-01-15T10:00:00Z"),
            ("open", None, None),
        ]):
            store.track_pr(f"run-{i}", 40 + i, f"url{i}", f"b{i}")
            if status != "open":
                store.update_outcome(
                    pr_number=40 + i,
                    status=status,
                    merged_at=merged_at,
                    closed_at=closed_at,
                )
        stats = compute_outcome_stats(tmp_repo)
        assert stats["total_tracked"] == 4
        assert stats["merged_count"] == 2
        assert stats["closed_count"] == 1
        assert stats["open_count"] == 1
        # merge_rate = merged / (merged + closed) = 2/3
        assert abs(stats["merge_rate"] - 2.0 / 3.0) < 0.01

    def test_avg_time_to_merge(self, store: OutcomeStore, tmp_repo: Path):
        base = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        # PR merged after 2 hours
        store.track_pr("run-1", 42, "url1", "b1")
        store._conn.execute(
            "UPDATE pr_outcomes SET status='merged', created_at=?, merged_at=? WHERE pr_number=42",
            (base.isoformat(), (base + timedelta(hours=2)).isoformat()),
        )
        # PR merged after 4 hours
        store.track_pr("run-2", 43, "url2", "b2")
        store._conn.execute(
            "UPDATE pr_outcomes SET status='merged', created_at=?, merged_at=? WHERE pr_number=43",
            (base.isoformat(), (base + timedelta(hours=4)).isoformat()),
        )
        store._conn.commit()

        stats = compute_outcome_stats(tmp_repo)
        # avg = (2 + 4) / 2 = 3.0 hours
        assert abs(stats["avg_time_to_merge_hours"] - 3.0) < 0.1


# ---------------------------------------------------------------------------
# 1.4 format_outcome_summary() tests
# ---------------------------------------------------------------------------


class TestFormatOutcomeSummary:
    def test_empty_outcomes_returns_empty(self, tmp_repo: Path):
        result = format_outcome_summary(tmp_repo)
        assert result == ""

    def test_compact_string_output(self, store: OutcomeStore, tmp_repo: Path):
        base = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            store.track_pr(f"run-{i}", 40 + i, f"url{i}", f"b{i}")
        # Merge 3, close 1, leave 1 open
        for i in range(3):
            store._conn.execute(
                "UPDATE pr_outcomes SET status='merged', created_at=?, merged_at=? WHERE pr_number=?",
                (base.isoformat(), (base + timedelta(hours=2)).isoformat(), 40 + i),
            )
        store._conn.execute(
            "UPDATE pr_outcomes SET status='closed', closed_at=?, close_context='too large' WHERE pr_number=44",
            ((base + timedelta(hours=1)).isoformat(),),
        )
        store._conn.commit()

        result = format_outcome_summary(tmp_repo)
        assert "merged" in result.lower()
        assert result != ""

    def test_token_budget(self, store: OutcomeStore, tmp_repo: Path):
        """Summary should stay under ~500 tokens (~2000 chars)."""
        base = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(50):
            store.track_pr(f"run-{i}", 100 + i, f"url{i}", f"branch-with-long-name-{i}")
            if i % 2 == 0:
                store._conn.execute(
                    "UPDATE pr_outcomes SET status='merged', created_at=?, merged_at=? WHERE pr_number=?",
                    (base.isoformat(), (base + timedelta(hours=i + 1)).isoformat(), 100 + i),
                )
        store._conn.commit()

        result = format_outcome_summary(tmp_repo)
        # ~500 tokens ≈ ~2000 chars
        assert len(result) <= 2000


# ---------------------------------------------------------------------------
# 3.1 Deliver phase integration tests
# ---------------------------------------------------------------------------


class TestRegisterPrOutcome:
    """Tests for _register_pr_outcome helper used by the deliver phase."""

    def test_registers_pr_with_correct_args(self, tmp_repo: Path):
        """track_pr is called with run_id, pr_number, pr_url, branch_name."""
        from colonyos.orchestrator import _register_pr_outcome

        with patch("colonyos.orchestrator.OutcomeStore") as MockStore:
            mock_instance = MagicMock()
            MockStore.return_value.__enter__ = MagicMock(return_value=mock_instance)
            MockStore.return_value.__exit__ = MagicMock(return_value=False)

            _register_pr_outcome(
                repo_root=tmp_repo,
                run_id="run-abc",
                pr_url="https://github.com/org/repo/pull/99",
                branch_name="colonyos/my-feature",
            )

            mock_instance.track_pr.assert_called_once_with(
                "run-abc", 99, "https://github.com/org/repo/pull/99", "colonyos/my-feature",
            )

    def test_not_called_when_no_pr_url(self, tmp_repo: Path):
        """_register_pr_outcome is a no-op when pr_url is empty."""
        from colonyos.orchestrator import _register_pr_outcome

        with patch("colonyos.orchestrator.OutcomeStore") as MockStore:
            _register_pr_outcome(
                repo_root=tmp_repo,
                run_id="run-abc",
                pr_url="",
                branch_name="colonyos/my-feature",
            )
            MockStore.assert_not_called()

    def test_not_called_when_pr_number_not_extractable(self, tmp_repo: Path):
        """_register_pr_outcome is a no-op when PR number can't be parsed."""
        from colonyos.orchestrator import _register_pr_outcome

        with patch("colonyos.orchestrator.OutcomeStore") as MockStore:
            _register_pr_outcome(
                repo_root=tmp_repo,
                run_id="run-abc",
                pr_url="https://github.com/org/repo/not-a-pull-url",
                branch_name="colonyos/my-feature",
            )
            MockStore.assert_not_called()

    def test_handles_track_pr_exception_gracefully(self, tmp_repo: Path):
        """Exceptions from track_pr are caught and logged, not raised."""
        from colonyos.orchestrator import _register_pr_outcome

        with patch("colonyos.orchestrator.OutcomeStore") as MockStore:
            mock_instance = MagicMock()
            mock_instance.track_pr.side_effect = Exception("DB locked")
            MockStore.return_value.__enter__ = MagicMock(return_value=mock_instance)
            MockStore.return_value.__exit__ = MagicMock(return_value=False)

            # Should NOT raise
            _register_pr_outcome(
                repo_root=tmp_repo,
                run_id="run-abc",
                pr_url="https://github.com/org/repo/pull/99",
                branch_name="colonyos/my-feature",
            )


# ---------------------------------------------------------------------------
# 5.1 CLI command tests
# ---------------------------------------------------------------------------

from click.testing import CliRunner
from colonyos.cli import app


@pytest.fixture
def cli_runner():
    return CliRunner()


class TestOutcomesCLI:
    """Tests for `colonyos outcomes` and `colonyos outcomes poll` commands."""

    def test_outcomes_displays_table(self, cli_runner: CliRunner, tmp_repo: Path):
        """outcomes command displays a Rich table with correct columns."""
        # Seed some data
        with OutcomeStore(tmp_repo) as store:
            store.track_pr("run-1", 42, "https://github.com/o/r/pull/42", "feat/x")
            store.track_pr("run-2", 43, "https://github.com/o/r/pull/43", "feat/y")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_repo):
            result = cli_runner.invoke(app, ["outcomes"])

        assert result.exit_code == 0
        # Check column headers are present
        assert "PR#" in result.output or "PR" in result.output
        assert "Status" in result.output
        assert "Branch" in result.output
        # Check data rows are present
        assert "42" in result.output
        assert "43" in result.output
        assert "feat/x" in result.output

    def test_outcomes_empty_shows_message(self, cli_runner: CliRunner, tmp_repo: Path):
        """Empty outcomes shows a helpful message instead of an empty table."""
        # Ensure .colonyos dir exists for OutcomeStore
        (tmp_repo / ".colonyos").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_repo):
            result = cli_runner.invoke(app, ["outcomes"])

        assert result.exit_code == 0
        assert "no tracked" in result.output.lower() or "no pr" in result.output.lower()

    def test_outcomes_status_colored(self, cli_runner: CliRunner, tmp_repo: Path):
        """Status values appear in the output (color applied via Rich)."""
        with OutcomeStore(tmp_repo) as store:
            store.track_pr("run-1", 42, "url1", "feat/x")
            store.update_outcome(pr_number=42, status="merged")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_repo):
            result = cli_runner.invoke(app, ["outcomes"])

        assert result.exit_code == 0
        assert "merged" in result.output.lower()

    def test_outcomes_poll_calls_poll_and_displays(self, cli_runner: CliRunner, tmp_repo: Path):
        """outcomes poll triggers poll_outcomes() then shows the updated table."""
        with OutcomeStore(tmp_repo) as store:
            store.track_pr("run-1", 42, "url1", "feat/x")

        with (
            patch("colonyos.cli._find_repo_root", return_value=tmp_repo),
            patch("colonyos.outcomes.poll_outcomes") as mock_poll,
        ):
            result = cli_runner.invoke(app, ["outcomes", "poll"])

        assert result.exit_code == 0
        mock_poll.assert_called_once_with(tmp_repo)
        # Table should still be displayed after polling
        assert "42" in result.output

    def test_outcomes_poll_handles_error(self, cli_runner: CliRunner, tmp_repo: Path):
        """outcomes poll handles poll_outcomes failures gracefully."""
        (tmp_repo / ".colonyos").mkdir(exist_ok=True)

        with (
            patch("colonyos.cli._find_repo_root", return_value=tmp_repo),
            patch("colonyos.outcomes.poll_outcomes", side_effect=Exception("gh not found")),
        ):
            result = cli_runner.invoke(app, ["outcomes", "poll"])

        # Should not crash — should show warning and still try to display table
        assert result.exit_code == 0

    def test_outcomes_no_subcommand_shows_table(self, cli_runner: CliRunner, tmp_repo: Path):
        """Bare `colonyos outcomes` (no subcommand) shows the table."""
        with OutcomeStore(tmp_repo) as store:
            store.track_pr("run-1", 42, "url1", "feat/x")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_repo):
            result = cli_runner.invoke(app, ["outcomes"])

        assert result.exit_code == 0
        assert "42" in result.output


# ---------------------------------------------------------------------------
# 7.1 Memory capture tests
# ---------------------------------------------------------------------------


class TestMemoryCapture:
    """Tests for memory capture when poll_outcomes detects PR closure."""

    def test_closed_pr_creates_failure_memory(self, store: OutcomeStore, tmp_repo: Path):
        """When poll_outcomes detects open→closed, a FAILURE MemoryEntry is created."""
        store.track_pr("run-1", 42, "url1", "feat/x")
        gh_data = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            comments=[{"body": "This PR is too large, please split."}],
        )
        with (
            patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data),
            patch("colonyos.outcomes.MemoryStore") as MockMemStore,
        ):
            mock_mem_instance = MagicMock()
            MockMemStore.return_value.__enter__ = MagicMock(return_value=mock_mem_instance)
            MockMemStore.return_value.__exit__ = MagicMock(return_value=False)

            poll_outcomes(tmp_repo)

            mock_mem_instance.add_memory.assert_called_once()
            call_kwargs = mock_mem_instance.add_memory.call_args
            # Check category is FAILURE
            from colonyos.memory import MemoryCategory
            assert call_kwargs.kwargs["category"] == MemoryCategory.FAILURE
            # Check phase is "deliver"
            assert call_kwargs.kwargs["phase"] == "deliver"
            # Check text contains PR number and reviewer feedback
            assert "PR #42" in call_kwargs.kwargs["text"]
            assert "closed without merge" in call_kwargs.kwargs["text"]
            assert "too large" in call_kwargs.kwargs["text"].lower()

    def test_merged_pr_does_not_create_memory(self, store: OutcomeStore, tmp_repo: Path):
        """No memory entry is created for merged PRs."""
        store.track_pr("run-1", 42, "url1", "feat/x")
        gh_data = _make_gh_result(
            state="MERGED",
            merged_at="2025-01-15T10:00:00Z",
            reviews=[{"body": "LGTM"}],
        )
        with (
            patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data),
            patch("colonyos.outcomes.MemoryStore") as MockMemStore,
        ):
            poll_outcomes(tmp_repo)
            MockMemStore.assert_not_called()

    def test_closed_pr_without_comments_no_memory(self, store: OutcomeStore, tmp_repo: Path):
        """No memory entry for PRs closed without any reviewer comment."""
        store.track_pr("run-1", 42, "url1", "feat/x")
        gh_data = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            # No comments or reviews — close_context will be empty
            comments=[],
            reviews=[],
        )
        with (
            patch("colonyos.outcomes._call_gh_pr_view", return_value=gh_data),
            patch("colonyos.outcomes.MemoryStore") as MockMemStore,
        ):
            poll_outcomes(tmp_repo)
            MockMemStore.assert_not_called()

    def test_memory_capture_failure_does_not_break_poll(self, store: OutcomeStore, tmp_repo: Path):
        """If MemoryStore.add_memory raises, poll_outcomes continues without crashing."""
        store.track_pr("run-1", 42, "url1", "feat/x")
        store.track_pr("run-2", 43, "url2", "feat/y")
        gh_data_closed = _make_gh_result(
            state="CLOSED",
            closed_at="2025-01-15T10:00:00Z",
            comments=[{"body": "Rejected: duplicate of another PR"}],
        )
        gh_data_merged = _make_gh_result(
            state="MERGED",
            merged_at="2025-01-15T12:00:00Z",
        )

        def mock_gh(pr_number, repo_root):
            if pr_number == 42:
                return gh_data_closed
            return gh_data_merged

        with (
            patch("colonyos.outcomes._call_gh_pr_view", side_effect=mock_gh),
            patch("colonyos.outcomes.MemoryStore") as MockMemStore,
        ):
            mock_mem_instance = MagicMock()
            mock_mem_instance.add_memory.side_effect = Exception("DB locked")
            MockMemStore.return_value.__enter__ = MagicMock(return_value=mock_mem_instance)
            MockMemStore.return_value.__exit__ = MagicMock(return_value=False)

            # Should NOT raise despite memory store failure
            poll_outcomes(tmp_repo)

        # PR 43 should still be updated to merged
        outcomes = store.get_outcomes()
        pr43 = [o for o in outcomes if o["pr_number"] == 43][0]
        assert pr43["status"] == "merged"
