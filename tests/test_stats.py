"""Tests for the colonyos.stats module."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from colonyos.stats import (
    DurationRow,
    ModelUsageRow,
    PhaseCostRow,
    PhaseDetailRow,
    PhaseFailureRow,
    RecentRunEntry,
    ReviewLoopStats,
    RunSummary,
    StatsResult,
    compute_cost_breakdown,
    compute_duration_stats,
    compute_failure_hotspots,
    compute_model_usage,
    compute_phase_detail,
    compute_recent_trend,
    compute_review_loop_stats,
    compute_run_summary,
    compute_stats,
    filter_runs,
    load_run_logs,
    render_cost_breakdown,
    render_dashboard,
    render_duration_stats,
    render_failure_hotspots,
    render_model_usage,
    render_phase_detail,
    render_recent_trend,
    render_review_loop_stats,
    render_run_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "run-001",
    status: str = "completed",
    total_cost_usd: float = 1.0,
    started_at: str = "2026-03-17T12:00:00+00:00",
    finished_at: str = "2026-03-17T12:10:00+00:00",
    phases: list[dict] | None = None,
) -> dict:
    """Build a minimal run log dict for testing."""
    return {
        "run_id": run_id,
        "status": status,
        "total_cost_usd": total_cost_usd,
        "started_at": started_at,
        "finished_at": finished_at,
        "phases": phases or [],
    }


def _make_phase(
    phase: str = "implement",
    success: bool = True,
    cost_usd: float | None = 0.5,
    duration_ms: int = 60000,
) -> dict:
    return {
        "phase": phase,
        "success": success,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    }


def _capture_console() -> Console:
    """Create a console that writes to a StringIO buffer."""
    return Console(file=StringIO(), force_terminal=True, width=120)


def _get_output(console: Console) -> str:
    f = console.file
    assert isinstance(f, StringIO)
    return f.getvalue()


# ---------------------------------------------------------------------------
# Task 1: Dataclass construction tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_run_summary_defaults(self):
        s = RunSummary()
        assert s.total_runs == 0
        assert s.total_cost_usd == 0.0

    def test_phase_cost_row_defaults(self):
        r = PhaseCostRow()
        assert r.phase == ""
        assert r.pct_of_total == 0.0

    def test_phase_failure_row_defaults(self):
        r = PhaseFailureRow()
        assert r.failure_rate == 0.0

    def test_review_loop_stats_defaults(self):
        r = ReviewLoopStats()
        assert r.avg_review_rounds == 0.0

    def test_duration_row_defaults(self):
        r = DurationRow()
        assert r.avg_duration_ms == 0

    def test_recent_run_entry_defaults(self):
        r = RecentRunEntry()
        assert r.status == ""

    def test_stats_result_defaults(self):
        r = StatsResult()
        assert r.summary.total_runs == 0
        assert r.cost_breakdown == []
        assert r.phase_filter is None


# ---------------------------------------------------------------------------
# Task 2: Run log loading and filtering
# ---------------------------------------------------------------------------


class TestLoadRunLogs:
    def test_empty_dir(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        assert load_run_logs(runs_dir) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert load_run_logs(tmp_path / "nope") == []

    def test_single_file(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        data = _make_run()
        (runs_dir / "run-001.json").write_text(json.dumps(data))
        result = load_run_logs(runs_dir)
        assert len(result) == 1
        assert result[0]["run_id"] == "run-001"

    def test_corrupted_file_skipped(self, tmp_path: Path, capsys):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        (runs_dir / "run-bad.json").write_text("{invalid json")
        (runs_dir / "run-good.json").write_text(json.dumps(_make_run()))
        result = load_run_logs(runs_dir)
        assert len(result) == 1
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_loop_state_excluded(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        (runs_dir / "run-001.json").write_text(json.dumps(_make_run()))
        (runs_dir / "loop_state_001.json").write_text(json.dumps({"loop": True}))
        result = load_run_logs(runs_dir)
        assert len(result) == 1

    def test_sorted_by_started_at_desc(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        r1 = _make_run(run_id="run-old", started_at="2026-03-15T00:00:00+00:00")
        r2 = _make_run(run_id="run-new", started_at="2026-03-17T00:00:00+00:00")
        (runs_dir / "run-old.json").write_text(json.dumps(r1))
        (runs_dir / "run-new.json").write_text(json.dumps(r2))
        result = load_run_logs(runs_dir)
        assert result[0]["run_id"] == "run-new"
        assert result[1]["run_id"] == "run-old"


class TestFilterRuns:
    def test_no_filter(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(5)]
        assert len(filter_runs(runs)) == 5

    def test_last_n(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(10)]
        assert len(filter_runs(runs, last=3)) == 3

    def test_last_larger_than_count(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(3)]
        assert len(filter_runs(runs, last=100)) == 3

    def test_last_none(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(5)]
        assert len(filter_runs(runs, last=None)) == 5


# ---------------------------------------------------------------------------
# Task 3: Computation functions
# ---------------------------------------------------------------------------


class TestComputeRunSummary:
    def test_empty(self):
        s = compute_run_summary([])
        assert s.total_runs == 0

    def test_single_completed(self):
        s = compute_run_summary([_make_run(status="completed", total_cost_usd=2.5)])
        assert s.total_runs == 1
        assert s.completed == 1
        assert s.failed == 0
        assert s.success_rate == 100.0
        assert s.total_cost_usd == 2.5

    def test_single_failed(self):
        s = compute_run_summary([_make_run(status="failed", total_cost_usd=1.0)])
        assert s.failed == 1
        assert s.failure_rate == 100.0

    def test_mixed(self):
        runs = [
            _make_run(status="completed", total_cost_usd=2.0),
            _make_run(status="failed", total_cost_usd=1.0),
            _make_run(status="completed", total_cost_usd=3.0),
        ]
        s = compute_run_summary(runs)
        assert s.total_runs == 3
        assert s.completed == 2
        assert s.failed == 1
        assert s.total_cost_usd == pytest.approx(6.0)
        assert s.success_rate == pytest.approx(66.6666, rel=0.01)

    def test_none_cost_treated_as_zero(self):
        s = compute_run_summary([_make_run(total_cost_usd=None)])
        assert s.total_cost_usd == 0.0

    def test_in_progress(self):
        s = compute_run_summary([_make_run(status="running")])
        assert s.in_progress == 1


class TestComputeCostBreakdown:
    def test_empty(self):
        assert compute_cost_breakdown([]) == []

    def test_single_phase(self):
        run = _make_run(phases=[_make_phase(phase="implement", cost_usd=1.0)])
        rows = compute_cost_breakdown([run])
        assert len(rows) == 1
        assert rows[0].phase == "implement"
        assert rows[0].total_cost == 1.0
        assert rows[0].pct_of_total == pytest.approx(100.0)

    def test_multiple_phases(self):
        run = _make_run(
            phases=[
                _make_phase(phase="plan", cost_usd=0.5),
                _make_phase(phase="implement", cost_usd=1.5),
            ]
        )
        rows = compute_cost_breakdown([run])
        assert len(rows) == 2
        total = sum(r.total_cost for r in rows)
        assert total == pytest.approx(2.0)

    def test_none_cost_excluded(self):
        run = _make_run(
            phases=[
                _make_phase(phase="plan", cost_usd=None),
                _make_phase(phase="implement", cost_usd=1.0),
            ]
        )
        rows = compute_cost_breakdown([run])
        assert len(rows) == 1
        assert rows[0].phase == "implement"

    def test_zero_occurrence_phases_omitted(self):
        run = _make_run(phases=[_make_phase(phase="implement", cost_usd=0.5)])
        rows = compute_cost_breakdown([run])
        phase_names = [r.phase for r in rows]
        assert "plan" not in phase_names


class TestComputeFailureHotspots:
    def test_empty(self):
        assert compute_failure_hotspots([]) == []

    def test_all_success(self):
        run = _make_run(phases=[_make_phase(success=True)])
        rows = compute_failure_hotspots([run])
        assert rows[0].failure_rate == 0.0

    def test_all_failure(self):
        run = _make_run(phases=[_make_phase(success=False)])
        rows = compute_failure_hotspots([run])
        assert rows[0].failure_rate == 100.0

    def test_mixed_sorted_desc(self):
        run = _make_run(
            phases=[
                _make_phase(phase="plan", success=True),
                _make_phase(phase="implement", success=False),
            ]
        )
        rows = compute_failure_hotspots([run])
        assert rows[0].phase == "implement"
        assert rows[0].failure_rate == 100.0
        assert rows[1].phase == "plan"
        assert rows[1].failure_rate == 0.0


class TestComputeReviewLoopStats:
    def test_no_reviews(self):
        run = _make_run(phases=[_make_phase(phase="implement")])
        stats = compute_review_loop_stats([run])
        assert stats.total_review_rounds == 0
        assert stats.avg_review_rounds == 0.0

    def test_single_review_round_approved(self):
        run = _make_run(
            phases=[
                _make_phase(phase="review"),
                _make_phase(phase="decision"),
            ]
        )
        stats = compute_review_loop_stats([run])
        assert stats.total_review_rounds == 1
        assert stats.first_pass_approval_rate == 100.0
        assert stats.total_fix_iterations == 0

    def test_review_fix_cycle(self):
        run = _make_run(
            phases=[
                _make_phase(phase="review"),
                _make_phase(phase="decision"),
                _make_phase(phase="fix"),
                _make_phase(phase="review"),
                _make_phase(phase="decision"),
            ]
        )
        stats = compute_review_loop_stats([run])
        assert stats.total_review_rounds == 2
        assert stats.total_fix_iterations == 1
        assert stats.first_pass_approval_rate == 0.0

    def test_parallel_reviews_one_round(self):
        """Four parallel review entries = 1 round."""
        run = _make_run(
            phases=[
                _make_phase(phase="review"),
                _make_phase(phase="review"),
                _make_phase(phase="review"),
                _make_phase(phase="review"),
                _make_phase(phase="decision"),
            ]
        )
        stats = compute_review_loop_stats([run])
        assert stats.total_review_rounds == 1

    def test_multiple_runs(self):
        run1 = _make_run(
            phases=[_make_phase(phase="review"), _make_phase(phase="decision")]
        )
        run2 = _make_run(
            phases=[
                _make_phase(phase="review"),
                _make_phase(phase="fix"),
                _make_phase(phase="review"),
                _make_phase(phase="decision"),
            ]
        )
        stats = compute_review_loop_stats([run1, run2])
        assert stats.total_review_rounds == 3
        assert stats.avg_review_rounds == pytest.approx(1.5)
        assert stats.first_pass_approval_rate == 50.0


class TestComputeDurationStats:
    def test_empty(self):
        assert compute_duration_stats([]) == []

    def test_single_run(self):
        run = _make_run(
            phases=[_make_phase(phase="implement", duration_ms=120000)],
            started_at="2026-03-17T12:00:00+00:00",
            finished_at="2026-03-17T12:10:00+00:00",
        )
        rows = compute_duration_stats([run])
        phase_rows = [r for r in rows if r.label != "Total (wall-clock)"]
        assert len(phase_rows) == 1
        assert phase_rows[0].avg_duration_ms == 120000

        total_rows = [r for r in rows if r.label == "Total (wall-clock)"]
        assert len(total_rows) == 1
        assert total_rows[0].avg_duration_ms == 600000  # 10 minutes

    def test_zero_duration(self):
        run = _make_run(phases=[_make_phase(duration_ms=0)])
        rows = compute_duration_stats([run])
        assert rows[0].avg_duration_ms == 0

    def test_multiple_runs(self):
        r1 = _make_run(phases=[_make_phase(phase="plan", duration_ms=10000)])
        r2 = _make_run(phases=[_make_phase(phase="plan", duration_ms=20000)])
        rows = compute_duration_stats([r1, r2])
        plan_rows = [r for r in rows if r.label == "plan"]
        assert plan_rows[0].avg_duration_ms == 15000


class TestComputeRecentTrend:
    def test_empty(self):
        assert compute_recent_trend([]) == []

    def test_fewer_than_10(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(3)]
        entries = compute_recent_trend(runs)
        assert len(entries) == 3

    def test_more_than_10(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(15)]
        entries = compute_recent_trend(runs)
        assert len(entries) == 10

    def test_exactly_10(self):
        runs = [_make_run(run_id=f"run-{i}") for i in range(10)]
        entries = compute_recent_trend(runs)
        assert len(entries) == 10


class TestComputePhaseDetail:
    def test_empty(self):
        assert compute_phase_detail([], "review") == []

    def test_filters_by_phase(self):
        run = _make_run(
            phases=[
                _make_phase(phase="plan", cost_usd=0.5),
                _make_phase(phase="implement", cost_usd=1.0),
            ]
        )
        rows = compute_phase_detail([run], "implement")
        assert len(rows) == 1
        assert rows[0].cost_usd == 1.0


class TestComputeStats:
    def test_integrates_all_sections(self):
        run = _make_run(
            phases=[
                _make_phase(phase="plan", cost_usd=0.5),
                _make_phase(phase="implement", cost_usd=1.0),
                _make_phase(phase="review", cost_usd=0.3),
                _make_phase(phase="decision", cost_usd=0.1),
            ]
        )
        result = compute_stats([run])
        assert result.summary.total_runs == 1
        assert len(result.cost_breakdown) > 0
        assert len(result.failure_hotspots) > 0
        assert len(result.duration_stats) > 0
        assert len(result.recent_trend) == 1

    def test_with_phase_filter(self):
        run = _make_run(
            phases=[_make_phase(phase="review", cost_usd=0.3)]
        )
        result = compute_stats([run], phase_filter="review")
        assert result.phase_filter == "review"
        assert len(result.phase_detail) == 1


# ---------------------------------------------------------------------------
# Task 4: Rendering tests
# ---------------------------------------------------------------------------


class TestRendering:
    def test_render_run_summary_no_crash(self):
        console = _capture_console()
        render_run_summary(console, RunSummary())
        output = _get_output(console)
        assert "Run Summary" in output

    def test_render_run_summary_with_data(self):
        console = _capture_console()
        summary = RunSummary(
            total_runs=5, completed=4, failed=1,
            success_rate=80.0, failure_rate=20.0, total_cost_usd=10.5,
        )
        render_run_summary(console, summary)
        output = _get_output(console)
        assert "80.0%" in output
        assert "$10.5000" in output

    def test_render_cost_breakdown_empty(self):
        console = _capture_console()
        render_cost_breakdown(console, [])
        assert _get_output(console) == ""

    def test_render_cost_breakdown_with_data(self):
        console = _capture_console()
        rows = [PhaseCostRow(phase="implement", total_cost=2.0, avg_cost=1.0, pct_of_total=60.0)]
        render_cost_breakdown(console, rows)
        output = _get_output(console)
        assert "implement" in output
        assert "60.0%" in output

    def test_render_failure_hotspots_empty(self):
        console = _capture_console()
        render_failure_hotspots(console, [])
        assert _get_output(console) == ""

    def test_render_failure_hotspots_with_data(self):
        console = _capture_console()
        rows = [PhaseFailureRow(phase="implement", executions=10, failures=2, failure_rate=20.0)]
        render_failure_hotspots(console, rows)
        output = _get_output(console)
        assert "implement" in output

    def test_render_review_loop_stats(self):
        console = _capture_console()
        stats = ReviewLoopStats(
            avg_review_rounds=1.5, first_pass_approval_rate=50.0,
            total_review_rounds=3, total_fix_iterations=1,
        )
        render_review_loop_stats(console, stats)
        output = _get_output(console)
        assert "Review Loop" in output
        assert "50.0%" in output

    def test_render_duration_stats_empty(self):
        console = _capture_console()
        render_duration_stats(console, [])
        assert _get_output(console) == ""

    def test_render_duration_stats_with_data(self):
        console = _capture_console()
        rows = [DurationRow(label="implement", avg_duration_ms=120000)]
        render_duration_stats(console, rows)
        output = _get_output(console)
        assert "implement" in output
        assert "2m" in output

    def test_render_recent_trend_empty(self):
        console = _capture_console()
        render_recent_trend(console, [])
        assert _get_output(console) == ""

    def test_render_recent_trend_with_data(self):
        console = _capture_console()
        entries = [
            RecentRunEntry(run_id="run-1", status="completed", cost_usd=1.0),
            RecentRunEntry(run_id="run-2", status="failed", cost_usd=0.5),
        ]
        render_recent_trend(console, entries)
        output = _get_output(console)
        assert "✓" in output
        assert "✗" in output

    def test_render_phase_detail_empty(self):
        console = _capture_console()
        render_phase_detail(console, [], "review")
        output = _get_output(console)
        assert "No data" in output

    def test_render_phase_detail_with_data(self):
        console = _capture_console()
        rows = [PhaseDetailRow(run_id="run-1", cost_usd=0.5, duration_ms=60000, success=True)]
        render_phase_detail(console, rows, "review")
        output = _get_output(console)
        assert "run-1" in output
        assert "$0.5000" in output

    def test_render_phase_detail_none_cost(self):
        console = _capture_console()
        rows = [PhaseDetailRow(run_id="run-1", cost_usd=None)]
        render_phase_detail(console, rows, "review")
        output = _get_output(console)
        assert "—" in output

    def test_render_dashboard_minimal(self):
        console = _capture_console()
        result = StatsResult()
        render_dashboard(console, result)
        output = _get_output(console)
        assert "Run Summary" in output

    def test_render_dashboard_full(self):
        console = _capture_console()
        result = StatsResult(
            summary=RunSummary(total_runs=1, completed=1, success_rate=100.0, total_cost_usd=2.0),
            cost_breakdown=[PhaseCostRow(phase="implement", total_cost=2.0, avg_cost=2.0, pct_of_total=100.0)],
            failure_hotspots=[PhaseFailureRow(phase="implement", executions=1, failures=0, failure_rate=0.0)],
            review_loop=ReviewLoopStats(avg_review_rounds=1.0, first_pass_approval_rate=100.0, total_review_rounds=1),
            duration_stats=[DurationRow(label="implement", avg_duration_ms=60000)],
            recent_trend=[RecentRunEntry(run_id="run-1", status="completed", cost_usd=2.0)],
        )
        render_dashboard(console, result)
        output = _get_output(console)
        assert "Run Summary" in output
        assert "Cost Breakdown" in output
        assert "Failure Hotspots" in output
        assert "Review Loop" in output


# ---------------------------------------------------------------------------
# Task: Model usage tests
# ---------------------------------------------------------------------------


class TestComputeModelUsage:
    def test_empty(self):
        assert compute_model_usage([]) == []

    def test_groups_by_model(self):
        run = _make_run(phases=[
            {**_make_phase(phase="implement", cost_usd=1.0), "model": "opus"},
            {**_make_phase(phase="review", cost_usd=0.5), "model": "sonnet"},
            {**_make_phase(phase="deliver", cost_usd=0.1), "model": "haiku"},
        ])
        rows = compute_model_usage([run])
        assert len(rows) == 3
        model_map = {r.model: r for r in rows}
        assert model_map["opus"].invocations == 1
        assert model_map["opus"].total_cost == pytest.approx(1.0)
        assert model_map["sonnet"].invocations == 1
        assert model_map["haiku"].total_cost == pytest.approx(0.1)

    def test_multiple_invocations_same_model(self):
        run = _make_run(phases=[
            {**_make_phase(phase="implement", cost_usd=1.0), "model": "opus"},
            {**_make_phase(phase="review", cost_usd=0.5), "model": "opus"},
        ])
        rows = compute_model_usage([run])
        assert len(rows) == 1
        assert rows[0].invocations == 2
        assert rows[0].total_cost == pytest.approx(1.5)
        assert rows[0].avg_cost == pytest.approx(0.75)

    def test_missing_model_field_grouped_as_unknown(self):
        run = _make_run(phases=[
            _make_phase(phase="implement", cost_usd=1.0),
        ])
        rows = compute_model_usage([run])
        assert len(rows) == 1
        assert rows[0].model == "unknown"

    def test_integrated_into_compute_stats(self):
        run = _make_run(phases=[
            {**_make_phase(phase="implement", cost_usd=1.0), "model": "opus"},
        ])
        result = compute_stats([run])
        assert len(result.model_usage) == 1
        assert result.model_usage[0].model == "opus"


class TestRenderModelUsage:
    def test_empty(self):
        console = _capture_console()
        render_model_usage(console, [])
        assert _get_output(console) == ""

    def test_with_data(self):
        console = _capture_console()
        rows = [
            ModelUsageRow(model="opus", invocations=5, total_cost=10.0, avg_cost=2.0),
            ModelUsageRow(model="haiku", invocations=3, total_cost=0.3, avg_cost=0.1),
        ]
        render_model_usage(console, rows)
        output = _get_output(console)
        assert "Model Usage" in output
        assert "opus" in output
        assert "haiku" in output

    def test_dashboard_includes_model_usage(self):
        console = _capture_console()
        result = StatsResult(
            model_usage=[
                ModelUsageRow(model="opus", invocations=2, total_cost=5.0, avg_cost=2.5),
            ],
        )
        render_dashboard(console, result)
        output = _get_output(console)
        assert "Model Usage" in output
