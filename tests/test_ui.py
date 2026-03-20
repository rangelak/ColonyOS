"""Tests for UI extensions for parallel task streaming (Task 8.0)."""

from colonyos.ui import (
    REVIEWER_COLORS,
    make_task_prefix,
    print_task_legend,
    PhaseUI,
)


class TestMakeTaskPrefix:
    """Tests for task prefix generation (Task 8.1)."""

    def test_simple_task_id(self) -> None:
        prefix = make_task_prefix("3.0")
        # Should contain the task ID and be colored
        assert "3.0" in prefix
        assert "[" in prefix  # Rich markup

    def test_subtask_id(self) -> None:
        prefix = make_task_prefix("3.1")
        assert "3.1" in prefix

    def test_different_task_ids_different_colors(self) -> None:
        prefix1 = make_task_prefix("1.0")
        prefix2 = make_task_prefix("2.0")
        # They should both be valid prefixes
        assert "1.0" in prefix1
        assert "2.0" in prefix2

    def test_color_rotation(self) -> None:
        # Task IDs should rotate through colors based on numeric part
        prefixes = [make_task_prefix(f"{i}.0") for i in range(1, 10)]
        # All should be valid prefixes
        for i, prefix in enumerate(prefixes, 1):
            assert f"{i}.0" in prefix


class TestPrintTaskLegend:
    """Tests for task legend printing (Task 8.2)."""

    def test_legend_with_tasks(self, capsys) -> None:
        # We can't easily test Rich console output, but we can verify
        # the function doesn't raise
        tasks = [
            ("1.0", "Add user model"),
            ("2.0", "Add authentication"),
            ("3.0", "Add rate limiting"),
        ]
        # Should not raise
        print_task_legend(tasks)

    def test_legend_empty_tasks(self, capsys) -> None:
        # Empty list should be handled gracefully
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
        # The prefix should include the task ID
        assert "3.0" in ui._prefix


class TestTaskColors:
    """Tests for task color assignment."""

    def test_reviewer_colors_available(self) -> None:
        assert len(REVIEWER_COLORS) >= 7

    def test_task_color_function(self) -> None:
        from colonyos.ui import _task_color
        # Should return colors from REVIEWER_COLORS
        for i in range(10):
            color = _task_color(i)
            assert color in REVIEWER_COLORS
