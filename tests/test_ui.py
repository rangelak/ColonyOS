"""Tests for UI module: parallel task streaming + ParallelProgressLine."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from colonyos.models import Phase, PhaseResult
from colonyos.ui import (
    REVIEWER_COLORS,
    make_task_prefix,
    make_reviewer_badge,
    print_task_legend,
    PhaseUI,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task prefix / legend / PhaseUI (parallel implement streaming)
# ---------------------------------------------------------------------------

class TestMakeTaskPrefix:
    """Tests for task prefix generation (Task 8.1)."""

    def test_simple_task_id(self) -> None:
        prefix = make_task_prefix("3.0")
        assert "3.0" in prefix
        assert "[" in prefix  # Rich markup

    def test_subtask_id(self) -> None:
        prefix = make_task_prefix("3.1")
        assert "3.1" in prefix

    def test_different_task_ids_different_colors(self) -> None:
        prefix1 = make_task_prefix("1.0")
        prefix2 = make_task_prefix("2.0")
        assert "1.0" in prefix1
        assert "2.0" in prefix2

    def test_color_rotation(self) -> None:
        prefixes = [make_task_prefix(f"{i}.0") for i in range(1, 10)]
        for i, prefix in enumerate(prefixes, 1):
            assert f"{i}.0" in prefix


class TestPrintTaskLegend:
    """Tests for task legend printing (Task 8.2)."""

    def test_legend_with_tasks(self, capsys) -> None:
        tasks = [
            ("1.0", "Add user model"),
            ("2.0", "Add authentication"),
            ("3.0", "Add rate limiting"),
        ]
        print_task_legend(tasks)

    def test_legend_empty_tasks(self, capsys) -> None:
        print_task_legend([])


class TestPhaseUIWithTaskId:
    """Tests for PhaseUI with task_id parameter (Task 8.5)."""

    def test_phase_ui_accepts_task_id(self) -> None:
        ui = PhaseUI(verbose=False, prefix="", task_id="3.0")
        assert ui._task_id == "3.0"

    def test_phase_ui_without_task_id(self) -> None:
        ui = PhaseUI(verbose=False)
        assert ui._task_id is None

    def test_phase_ui_task_id_affects_prefix(self) -> None:
        ui = PhaseUI(verbose=False, task_id="3.0")
        assert "3.0" in ui._prefix


class TestTaskColors:
    """Tests for task color assignment."""

    def test_reviewer_colors_available(self) -> None:
        assert len(REVIEWER_COLORS) >= 7

    def test_task_color_function(self) -> None:
        from colonyos.ui import _task_color
        for i in range(10):
            color = _task_color(i)
            assert color in REVIEWER_COLORS


class TestReviewerBadges:
    """Tests for stable reviewer badge generation."""

    def test_make_reviewer_badge_uses_expected_label_and_color(self) -> None:
        badge = make_reviewer_badge(1)
        assert badge.text == "R2"
        assert badge.style == REVIEWER_COLORS[1]
        assert "R2" in badge.markup


# ---------------------------------------------------------------------------
# ParallelProgressLine (review progress tracker)
# ---------------------------------------------------------------------------

class TestParallelProgressLine:
    """Tests for ParallelProgressLine class."""

    def test_initialization_with_reviewers(self) -> None:
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Linus Torvalds"), (1, "Steve Jobs")]
        tracker = ParallelProgressLine(reviewers, is_tty=True)

        assert tracker._reviewers == reviewers
        assert tracker._is_tty is True
        assert len(tracker._states) == 2

    def test_initialization_non_tty(self) -> None:
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False)

        assert tracker._is_tty is False

    def test_on_reviewer_complete_updates_state(self) -> None:
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer 1"), (1, "Reviewer 2")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, cost_usd=0.15, duration_ms=2000)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "approved"
        assert tracker._states[0]["cost_usd"] == 0.15
        assert tracker._states[0]["duration_ms"] == 2000

    def test_on_reviewer_complete_detects_request_changes(self) -> None:
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, approved=False)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "request-changes"

    def test_on_reviewer_complete_detects_failure(self) -> None:
        from colonyos.ui import ParallelProgressLine

        reviewers = [(0, "Reviewer")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=MagicMock())

        result = _fake_phase_result(0, success=False)
        tracker.on_reviewer_complete(0, result)

        assert tracker._states[0]["status"] == "failed"

    def test_render_tty_mode_produces_inline_format(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        result = _fake_phase_result(0, cost_usd=0.12)
        tracker.on_reviewer_complete(0, result)

        assert mock_console.print.called

    def test_render_non_tty_mode_produces_log_lines(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "Reviewer 1")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=mock_console)

        result = _fake_phase_result(0, cost_usd=0.12, duration_ms=2500)
        tracker.on_reviewer_complete(0, result)

        assert mock_console.print.called
        call_args = str(mock_console.print.call_args)
        assert "R1" in call_args or "Reviewer" in call_args
        assert make_reviewer_badge(0).markup in call_args

    def test_render_non_tty_multiple_completions_out_of_order(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "Alice"), (1, "Bob"), (2, "Charlie"), (3, "Diana")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=mock_console)

        tracker.on_reviewer_complete(2, _fake_phase_result(2, cost_usd=0.10))
        tracker.on_reviewer_complete(0, _fake_phase_result(0, cost_usd=0.12))
        tracker.on_reviewer_complete(3, _fake_phase_result(3, cost_usd=0.08))
        tracker.on_reviewer_complete(1, _fake_phase_result(1, cost_usd=0.15))

        assert mock_console.print.call_count == 4

        printed_lines = [str(call) for call in mock_console.print.call_args_list]

        r1_calls = [line for line in printed_lines if make_reviewer_badge(0).markup in line]
        r2_calls = [line for line in printed_lines if make_reviewer_badge(1).markup in line]
        r3_calls = [line for line in printed_lines if make_reviewer_badge(2).markup in line]
        r4_calls = [line for line in printed_lines if make_reviewer_badge(3).markup in line]

        assert len(r1_calls) == 1, f"R1 should appear once, got {len(r1_calls)}"
        assert len(r2_calls) == 1, f"R2 should appear once, got {len(r2_calls)}"
        assert len(r3_calls) == 1, f"R3 should appear once, got {len(r3_calls)}"
        assert len(r4_calls) == 1, f"R4 should appear once, got {len(r4_calls)}"

        assert "R3" in printed_lines[0], "First print should be R3 (index 2)"
        assert "R1" in printed_lines[1], "Second print should be R1 (index 0)"
        assert "R4" in printed_lines[2], "Third print should be R4 (index 3)"
        assert "R2" in printed_lines[3], "Fourth print should be R2 (index 1)"

    def test_cost_accumulation(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        tracker.on_reviewer_complete(0, _fake_phase_result(0, cost_usd=0.10))
        tracker.on_reviewer_complete(1, _fake_phase_result(1, cost_usd=0.15))

        assert tracker.total_cost_usd == pytest.approx(0.25)

    def test_completed_count(self) -> None:
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
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "\x1b[31mMalicious\x1b[0m Name")]
        tracker = ParallelProgressLine(reviewers, is_tty=False, console=mock_console)

        assert "\x1b" not in tracker._sanitized_names[0]
        assert "Malicious" in tracker._sanitized_names[0]

    def test_print_summary(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        tracker.on_reviewer_complete(0, _fake_phase_result(0, cost_usd=0.10, approved=True))
        tracker.on_reviewer_complete(1, _fake_phase_result(1, cost_usd=0.15, approved=False))

        tracker.print_summary(round_num=1)

        assert mock_console.print.called
        calls = [str(c) for c in mock_console.print.call_args_list]
        summary_call = [c for c in calls if "Review round" in c or "approved" in c]
        assert len(summary_call) > 0

    def test_elapsed_time_for_running_reviewers(self) -> None:
        from colonyos.ui import ParallelProgressLine

        mock_console = MagicMock()
        reviewers = [(0, "R1"), (1, "R2")]
        tracker = ParallelProgressLine(reviewers, is_tty=True, console=mock_console)

        time.sleep(0.01)

        tracker._render()

        assert mock_console.print.called
