"""Tests for the colonyos.ci module — CI log fetching, parsing, and prompt formatting."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from colonyos.ci import (
    CheckResult,
    _extract_run_id_from_url,
    _parse_and_truncate_logs,
    _truncate_tail_biased,
    all_checks_pass,
    check_pr_author_mismatch,
    collect_ci_failure_context,
    extract_run_id_from_url,
    fetch_check_logs,
    fetch_pr_checks,
    format_ci_failures_as_prompt,
    get_failed_checks,
    parse_pr_ref,
    poll_pr_checks,
    validate_branch_not_behind,
    validate_clean_worktree,
    validate_gh_auth,
)


class TestParsePrRef:
    def test_bare_number(self) -> None:
        assert parse_pr_ref("42") == 42

    def test_full_url(self) -> None:
        assert parse_pr_ref("https://github.com/org/repo/pull/99") == 99

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid PR reference"):
            parse_pr_ref("not-a-pr")

    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            parse_pr_ref("0")

    def test_whitespace_stripped(self) -> None:
        assert parse_pr_ref("  42  ") == 42


class TestFetchPrChecks:
    def test_success(self, tmp_path: Path) -> None:
        mock_output = json.dumps([
            {"name": "test", "state": "completed", "conclusion": "success", "detailsUrl": ""},
            {"name": "lint", "state": "completed", "conclusion": "failure", "detailsUrl": "http://x/runs/123"},
        ])
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            checks = fetch_pr_checks(42, tmp_path)
        assert len(checks) == 2
        assert checks[0].name == "test"
        assert checks[0].conclusion == "success"
        assert checks[1].conclusion == "failure"

    def test_gh_not_found(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(click.ClickException, match="gh.*not found"):
                fetch_pr_checks(1, tmp_path)

    def test_timeout(self, tmp_path: Path) -> None:
        import subprocess
        with patch("colonyos.ci.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 10)):
            with pytest.raises(click.ClickException, match="Timed out"):
                fetch_pr_checks(1, tmp_path)

    def test_nonzero_exit(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth error")
            with pytest.raises(click.ClickException, match="auth error"):
                fetch_pr_checks(1, tmp_path)


class TestFetchCheckLogs:
    def test_success(self, tmp_path: Path) -> None:
        mock_output = "job1\tstep1\tError: missing import\njob1\tstep1\tat line 42"
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            logs = fetch_check_logs("123", tmp_path)
        assert "job1 / step1" in logs
        assert "missing import" in logs["job1 / step1"]

    def test_gh_not_found(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(click.ClickException, match="gh.*not found"):
                fetch_check_logs("123", tmp_path)


class TestTruncation:
    def test_short_text_not_truncated(self) -> None:
        text = "hello"
        assert _truncate_tail_biased(text, 100) == text

    def test_long_text_truncated_tail_biased(self) -> None:
        lines = [f"line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = _truncate_tail_biased(text, 200)
        assert result.startswith("[...")
        assert "truncated" in result
        # End of text is preserved
        assert "line 99" in result

    def test_parse_and_truncate_logs(self) -> None:
        raw = "job\tstep\tline1\njob\tstep\tline2"
        result = _parse_and_truncate_logs(raw, 10000)
        assert "job / step" in result
        assert "line1" in result["job / step"]


class TestFormatCiFailures:
    def test_formats_with_delimiters(self) -> None:
        failures = [
            {"name": "test-job", "conclusion": "failure", "log": "Error: import failed"},
        ]
        result = format_ci_failures_as_prompt(failures)
        assert '<ci_failure_log step="test-job"' in result
        assert "</ci_failure_log>" in result
        assert "import failed" in result

    def test_sanitizes_secrets(self) -> None:
        failures = [
            {"name": "build", "conclusion": "failure", "log": "token=ghp_abc123secret"},
        ]
        result = format_ci_failures_as_prompt(failures)
        assert "ghp_abc123secret" not in result
        assert "[REDACTED]" in result

    def test_empty_failures(self) -> None:
        result = format_ci_failures_as_prompt([])
        assert result == ""


class TestPreflightChecks:
    def test_clean_worktree_passes(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            validate_clean_worktree(tmp_path)  # Should not raise

    def test_dirty_worktree_raises(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
            with pytest.raises(click.ClickException, match="uncommitted changes"):
                validate_clean_worktree(tmp_path)

    def test_branch_not_behind_passes(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            validate_branch_not_behind(tmp_path)  # Should not raise

    def test_branch_behind_raises(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            # First call is git fetch, second is rev-list
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # fetch
                MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-list
            ]
            with pytest.raises(click.ClickException, match="behind the remote"):
                validate_branch_not_behind(tmp_path)


class TestExtractRunId:
    def test_extracts_from_url(self) -> None:
        url = "https://github.com/org/repo/actions/runs/12345/jobs/678"
        assert _extract_run_id_from_url(url) == "12345"

    def test_returns_none_for_invalid(self) -> None:
        assert _extract_run_id_from_url("https://example.com") is None


class TestCheckHelpers:
    def test_get_failed_checks(self) -> None:
        checks = [
            CheckResult(name="test", state="completed", conclusion="success"),
            CheckResult(name="lint", state="completed", conclusion="failure"),
        ]
        failed = get_failed_checks(checks)
        assert len(failed) == 1
        assert failed[0].name == "lint"

    def test_all_checks_pass_true(self) -> None:
        checks = [
            CheckResult(name="test", state="completed", conclusion="success"),
        ]
        assert all_checks_pass(checks) is True

    def test_all_checks_pass_false(self) -> None:
        checks = [
            CheckResult(name="test", state="completed", conclusion="failure"),
        ]
        assert all_checks_pass(checks) is False


class TestPollPrChecks:
    def test_immediate_completion(self, tmp_path: Path) -> None:
        checks = [CheckResult(name="test", state="completed", conclusion="success")]
        with patch("colonyos.ci.fetch_pr_checks", return_value=checks):
            result = poll_pr_checks(42, tmp_path, timeout=10)
        assert len(result) == 1

    def test_timeout_raises(self, tmp_path: Path) -> None:
        checks = [CheckResult(name="test", state="in_progress", conclusion="")]
        with patch("colonyos.ci.fetch_pr_checks", return_value=checks):
            with patch("colonyos.ci.time.sleep"):
                with pytest.raises(click.ClickException, match="Timed out"):
                    poll_pr_checks(42, tmp_path, timeout=0, initial_interval=1)

    def test_empty_state_not_treated_as_terminal(self, tmp_path: Path) -> None:
        """Checks with empty state should not be considered complete."""
        pending = [CheckResult(name="test", state="", conclusion="")]
        completed = [CheckResult(name="test", state="completed", conclusion="success")]
        with patch("colonyos.ci.fetch_pr_checks", side_effect=[pending, completed]):
            with patch("colonyos.ci.time.sleep"):
                result = poll_pr_checks(42, tmp_path, timeout=60, initial_interval=1)
        assert len(result) == 1
        assert result[0].conclusion == "success"


class TestValidateGhAuth:
    def test_success(self) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            validate_gh_auth()  # Should not raise

    def test_not_authenticated(self) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with pytest.raises(click.ClickException, match="not authenticated"):
                validate_gh_auth()

    def test_gh_not_found(self) -> None:
        with patch("colonyos.ci.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(click.ClickException, match="not found"):
                validate_gh_auth()

    def test_timeout(self) -> None:
        import subprocess
        with patch("colonyos.ci.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 10)):
            with pytest.raises(click.ClickException, match="Timed out"):
                validate_gh_auth()


class TestCheckPrAuthorMismatch:
    def test_same_author_returns_none(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="alice\n"),  # PR author
                MagicMock(returncode=0, stdout="alice\n"),  # auth user
            ]
            assert check_pr_author_mismatch(42, tmp_path) is None

    def test_different_author_returns_warning(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="mallory\n"),  # PR author
                MagicMock(returncode=0, stdout="alice\n"),    # auth user
            ]
            warning = check_pr_author_mismatch(42, tmp_path)
            assert warning is not None
            assert "mallory" in warning
            assert "alice" in warning
            assert "WARNING" in warning

    def test_api_failure_returns_none(self, tmp_path: Path) -> None:
        with patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert check_pr_author_mismatch(42, tmp_path) is None


class TestCollectCiFailureContext:
    def test_collects_from_failed_checks(self, tmp_path: Path) -> None:
        checks = [
            CheckResult(name="lint", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/123/jobs/1"),
            CheckResult(name="test", state="completed", conclusion="success"),
        ]
        mock_logs = {"step1": "Error: syntax error"}
        with patch("colonyos.ci.fetch_check_logs", return_value=mock_logs):
            result = collect_ci_failure_context(checks, tmp_path)
        assert len(result) == 1
        assert "lint" in result[0]["name"]
        assert "syntax error" in result[0]["log"]

    def test_no_run_id_fallback(self, tmp_path: Path) -> None:
        checks = [
            CheckResult(name="lint", state="completed", conclusion="failure",
                        details_url="https://example.com/no-run-id"),
        ]
        result = collect_ci_failure_context(checks, tmp_path)
        assert len(result) == 1
        assert "Could not fetch logs" in result[0]["log"]


class TestFormatCiFailuresTotalCap:
    def test_aggregate_cap_limits_output(self) -> None:
        failures = [
            {"name": f"step-{i}", "conclusion": "failure", "log": "x" * 1000}
            for i in range(5)
        ]
        # Cap at 2500 chars total — only first 2 steps fit fully
        result = format_ci_failures_as_prompt(failures, total_char_cap=2500)
        assert "aggregate log size cap reached" in result

    def test_under_cap_includes_all(self) -> None:
        failures = [
            {"name": "step-0", "conclusion": "failure", "log": "short"},
        ]
        result = format_ci_failures_as_prompt(failures, total_char_cap=100_000)
        assert "aggregate log size cap" not in result
        assert "short" in result


class TestExtractRunIdPublic:
    def test_public_alias_matches_private(self) -> None:
        url = "https://github.com/org/repo/actions/runs/99999/jobs/1"
        assert extract_run_id_from_url(url) == _extract_run_id_from_url(url)
        assert extract_run_id_from_url(url) == "99999"

    def test_non_string_returns_none(self) -> None:
        assert extract_run_id_from_url(None) is None  # type: ignore[arg-type]
