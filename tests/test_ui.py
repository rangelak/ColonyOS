"""Tests for the UI module, focusing on ParallelProgressLine."""
from __future__ import annotations

import io
import sys
from unittest.mock import patch, MagicMock

import pytest

from colonyos.models import Phase, PhaseResult


def _fake_phase_result(
    idx: int,
    success: bool = True,
    cost_usd: float = 0.1,
    duration_ms: int = 1000,
    approved: bool = True,
) -> PhaseResult:
    """Create a fake PhaseResult for testing."""
    verdict = "approve" if approved else "request-changes"
    return PhaseResult(
        phase=Phase.REVIEW,
        success=success,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        session_id=f"session-{idx}",
        artifacts={"result": f"VERDICT: {verdict}\n\nFINDINGS:\n- Test finding"},
    )


class TestParallelProgressLine:
    """Tests for ParallelProgressLine class."""

    def test_initialization_with_reviewers(self) -> None:
        """Test that ParallelProgressLine initializes with reviewer list."""
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Linus Torvalds"), (1, "Steve Jobs")]
        tracker = ParallelProgressLine(reviewers, is_tty=True)

        assert tracker._reviewers == reviewers
        assert tracker._is_tty is True
        assert len(tracker._states) == 2

    def test_initialization_non_tty(self) -> None:
        """Test initialization in non-TTY mode."""
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False)

        assert tracker._is_tty is False

    def test_on_reviewer_complete_updates_state(self) -> None:
        """Test that on_reviewer_complete updates internal state."""
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer 1"), (1, "Reviewer 2")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, cost_usd=0.15, duration_ms=2000)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "approved"
        assert tracker._states[0]["cost_usd"] == 0.15
        assert tracker._states[0]["duration_ms"] == 2000

    def test_on_reviewer_complete_detects_request_changes(self) -> None:
        """Test that on_reviewer_complete detects request-changes verdict."""
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, approved=False)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "request-changes"

    def test_on_reviewer_complete_detects_failure(self) -> None:
        """Test that on_reviewer_complete detects failed reviews."""
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, success=False)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "failed"

    def test_render_tty_mode_produces_inline_format(self) -> None:
        """Test that render() in TTY mode produces single-line progress."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        # Complete first reviewer
        result = _fake_phase_result(0, cost_usd=0.12)
        tracker.on_reviewer_complete(0, result)

        # Check that console.print was called
        assert mock_console.print.called

    def test_render_non_tty_mode_produces_log_lines(self) -> None:
        """Test that render() in non-TTY mode produces log-style output."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "Reviewer 1")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=mock_console)

        result = _fake_phase_result(0, cost_usd=0.12, duration_ms=2500)
        tracker.on_reviewer_complete(0, result)

        # Should have printed a log-style line
        assert mock_console.print.called
        call_args = str(mock_console.print.call_args)
        # Should contain reviewer info
        assert "R1" in call_args or "Reviewer" in call_args

    def test_cost_accumulation(self) -> None:
        """Test that costs accumulate across reviewers."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        tracker.on_reviewer_complete(0, _fake_phase_result(0, cost_usd=0.10))
        tracker.on_reviewer_complete(1, _fake_phase_result(1, cost_usd=0.15))

        assert tracker.total_cost_usd == pytest.approx(0.25)

    def test_completed_count(self) -> None:
        """Test that completed count is tracked correctly."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2"), (2, "R3")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        assert tracker.completed_count == 0

        tracker.on_reviewer_complete(0, _fake_phase_result(0))
        assert tracker.completed_count == 1

        tracker.on_reviewer_complete(2, _fake_phase_result(2))
        assert tracker.completed_count == 2

    def test_sanitizes_reviewer_names(self) -> None:
        """Test that reviewer names are sanitized before display."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        # Include ANSI escape in name
        reviewers = [(0, "\x1b[31mMalicious\x1b[0m Name")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=mock_console)

        # The stored name should be sanitized
        assert "\x1b" not in tracker._sanitized_names[0]
        assert "Malicious" in tracker._sanitized_names[0]

    def test_print_summary(self) -> None:
        """Test that print_summary outputs correct format."""
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        tracker.on_reviewer_complete(0, _fake_phase_result(0, cost_usd=0.10, approved=True))
        tracker.on_reviewer_complete(1, _fake_phase_result(1, cost_usd=0.15, approved=False))

        tracker.print_summary(round_num=1)

        # Check summary was printed
        assert mock_console.print.called
        # Find the summary call - should contain "approved" and "request-changes"
        calls = [str(c) for c in mock_console.print.call_args_list]
        summary_call = [c for c in calls if "Review round" in c or "approved" in c]
        assert len(summary_call) > 0

    def test_elapsed_time_for_running_reviewers(self) -> None:
        """Test elapsed time calculation for in-progress reviewers."""
        from colonyos.ui import ParallelProgressLine
        import time

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        # Wait a tiny bit to ensure some elapsed time
        time.sleep(0.01)

        # Render should show elapsed time for pending reviewers
        tracker._render()

        # The render should have been called
        assert mock_console.print.called
