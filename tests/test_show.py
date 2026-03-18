"""Tests for the colonyos.show module."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from colonyos.show import (
    PhaseTimelineEntry,
    ReviewSummary,
    RunHeader,
    ShowResult,
    collapse_phase_timeline,
    compute_review_summary,
    compute_run_header,
    compute_show_result,
    load_single_run,
    render_artifact_links,
    render_phase_detail,
    render_phase_timeline,
    render_review_summary,
    render_run_header,
    render_show,
    resolve_run_id,
    validate_run_id_input,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "run-20260317_120000-abc123",
    status: str = "completed",
    total_cost_usd: float = 5.0,
    started_at: str = "2026-03-17T12:00:00+00:00",
    finished_at: str = "2026-03-17T12:10:00+00:00",
    prompt: str = "Add a new feature",
    branch_name: str | None = "colonyos/feature",
    prd_rel: str | None = "cOS_prds/prd.md",
    task_rel: str | None = "cOS_tasks/tasks.md",
    phases: list[dict] | None = None,
    **kwargs,
) -> dict:
    data = {
        "run_id": run_id,
        "status": status,
        "total_cost_usd": total_cost_usd,
        "started_at": started_at,
        "finished_at": finished_at,
        "prompt": prompt,
        "branch_name": branch_name,
        "prd_rel": prd_rel,
        "task_rel": task_rel,
        "phases": phases or [],
    }
    data.update(kwargs)
    return data


def _make_phase(
    phase: str = "implement",
    success: bool = True,
    cost_usd: float | None = 0.5,
    duration_ms: int = 60000,
    model: str | None = "sonnet",
    session_id: str = "sess-001",
    error: str | None = None,
) -> dict:
    return {
        "phase": phase,
        "success": success,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "model": model,
        "session_id": session_id,
        "error": error,
    }


def _capture_console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _get_output(console: Console) -> str:
    f = console.file
    assert isinstance(f, StringIO)
    return f.getvalue()


def _create_run_file(runs_dir: Path, run_id: str, data: dict | None = None) -> Path:
    """Write a run JSON file to the given runs directory."""
    if data is None:
        data = _make_run(run_id=run_id)
    file_path = runs_dir / f"{run_id}.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# Task 1.1: resolve_run_id tests
# ---------------------------------------------------------------------------


class TestValidateRunIdInput:
    def test_rejects_forward_slash(self):
        with pytest.raises(ValueError, match="must not contain"):
            validate_run_id_input("../../etc/passwd")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="must not contain"):
            validate_run_id_input("run\\something")

    def test_rejects_dot_dot(self):
        with pytest.raises(ValueError, match="must not contain"):
            validate_run_id_input("run..test")

    def test_accepts_normal_id(self):
        validate_run_id_input("run-20260317_120000-abc123")

    def test_accepts_short_prefix(self):
        validate_run_id_input("abc1")


class TestResolveRunId:
    def test_exact_match(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        _create_run_file(runs_dir, "run-20260317_120000-abc123")

        result = resolve_run_id(runs_dir, "run-20260317_120000-abc123")
        assert result == "run-20260317_120000-abc123"

    def test_prefix_match(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        _create_run_file(runs_dir, "run-20260317_120000-abc123")

        result = resolve_run_id(runs_dir, "run-20260317_12")
        assert result == "run-20260317_120000-abc123"

    def test_hash_suffix_match(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        _create_run_file(runs_dir, "run-20260317_120000-abc123")

        result = resolve_run_id(runs_dir, "abc123")
        assert result == "run-20260317_120000-abc123"

    def test_zero_matches(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        _create_run_file(runs_dir, "run-20260317_120000-abc123")

        with pytest.raises(FileNotFoundError, match="No run found"):
            resolve_run_id(runs_dir, "xyz999")

    def test_multiple_matches_returns_list(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        _create_run_file(runs_dir, "run-20260317_120000-abc123")
        _create_run_file(runs_dir, "run-20260317_120100-abc456")

        result = resolve_run_id(runs_dir, "run-20260317_12")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_path_traversal_rejected(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        with pytest.raises(ValueError):
            resolve_run_id(runs_dir, "../etc/passwd")

    def test_runs_dir_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Runs directory"):
            resolve_run_id(tmp_path / "nonexistent", "abc")


# ---------------------------------------------------------------------------
# Task 1.2: load_single_run tests
# ---------------------------------------------------------------------------


class TestLoadSingleRun:
    def test_valid_file(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        data = _make_run()
        _create_run_file(runs_dir, "run-20260317_120000-abc123", data)

        result = load_single_run(runs_dir, "run-20260317_120000-abc123")
        assert result["run_id"] == "run-20260317_120000-abc123"
        assert result["status"] == "completed"

    def test_missing_file(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            load_single_run(runs_dir, "run-nonexistent")

    def test_corrupted_json(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        bad_file = runs_dir / "run-bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_single_run(runs_dir, "run-bad")


# ---------------------------------------------------------------------------
# Task 2.1: compute_run_header tests
# ---------------------------------------------------------------------------


class TestComputeRunHeader:
    def test_basic_metadata(self):
        run = _make_run()
        header = compute_run_header(run)
        assert header.run_id == "run-20260317_120000-abc123"
        assert header.status == "completed"
        assert header.total_cost_usd == 5.0
        assert header.branch_name == "colonyos/feature"

    def test_prompt_truncation(self):
        long_prompt = "A" * 200
        run = _make_run(prompt=long_prompt)
        header = compute_run_header(run)
        assert len(header.prompt_truncated) == 120
        assert header.prompt_truncated.endswith("...")
        assert header.prompt == long_prompt

    def test_short_prompt_not_truncated(self):
        run = _make_run(prompt="short")
        header = compute_run_header(run)
        assert header.prompt_truncated == "short"

    def test_wall_clock_duration(self):
        run = _make_run(
            started_at="2026-03-17T12:00:00+00:00",
            finished_at="2026-03-17T12:10:00+00:00",
        )
        header = compute_run_header(run)
        assert header.wall_clock_ms == 600000  # 10 minutes

    def test_no_finished_at(self):
        run = _make_run(finished_at=None)
        header = compute_run_header(run)
        assert header.wall_clock_ms == 0

    def test_source_issue_url(self):
        run = _make_run(source_issue_url="https://github.com/org/repo/issues/42")
        header = compute_run_header(run)
        assert header.source_issue_url == "https://github.com/org/repo/issues/42"

    def test_last_successful_phase(self):
        run = _make_run(last_successful_phase="implement")
        header = compute_run_header(run)
        assert header.last_successful_phase == "implement"


# ---------------------------------------------------------------------------
# Task 2.2: collapse_phase_timeline tests
# ---------------------------------------------------------------------------


class TestCollapsePhaseTimeline:
    def test_empty_phases(self):
        assert collapse_phase_timeline([]) == []

    def test_non_review_phases_preserved(self):
        phases = [
            _make_phase(phase="plan"),
            _make_phase(phase="implement"),
        ]
        entries = collapse_phase_timeline(phases)
        assert len(entries) == 2
        assert entries[0].phase == "plan"
        assert entries[1].phase == "implement"
        assert not entries[0].is_collapsed
        assert not entries[1].is_collapsed

    def test_single_review_not_collapsed(self):
        phases = [_make_phase(phase="review")]
        entries = collapse_phase_timeline(phases)
        assert len(entries) == 1
        assert entries[0].phase == "review"
        assert not entries[0].is_collapsed
        assert entries[0].round_number == 1

    def test_contiguous_reviews_collapsed(self):
        phases = [
            _make_phase(phase="review", cost_usd=1.0, duration_ms=10000),
            _make_phase(phase="review", cost_usd=2.0, duration_ms=20000),
            _make_phase(phase="review", cost_usd=3.0, duration_ms=30000),
        ]
        entries = collapse_phase_timeline(phases)
        assert len(entries) == 1
        assert entries[0].is_collapsed
        assert entries[0].collapsed_count == 3
        assert entries[0].phase == "review x3"
        assert entries[0].cost_usd == 6.0
        assert entries[0].duration_ms == 60000
        assert entries[0].round_number == 1

    def test_fix_starts_new_round(self):
        phases = [
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="fix"),
            _make_phase(phase="review"),
        ]
        entries = collapse_phase_timeline(phases)
        # review x2 (round 1), fix, review (round 2)
        assert len(entries) == 3
        assert entries[0].is_collapsed
        assert entries[0].round_number == 1
        assert entries[1].phase == "fix"
        assert entries[2].phase == "review"
        assert entries[2].round_number == 2

    def test_mixed_phases(self):
        phases = [
            _make_phase(phase="plan"),
            _make_phase(phase="implement"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="decision"),
            _make_phase(phase="deliver"),
        ]
        entries = collapse_phase_timeline(phases)
        assert len(entries) == 5
        assert entries[0].phase == "plan"
        assert entries[1].phase == "implement"
        assert entries[2].is_collapsed
        assert entries[2].collapsed_count == 3
        assert entries[3].phase == "decision"
        assert entries[4].phase == "deliver"

    def test_review_failure_propagated(self):
        phases = [
            _make_phase(phase="review", success=True),
            _make_phase(phase="review", success=False),
        ]
        entries = collapse_phase_timeline(phases)
        assert len(entries) == 1
        assert not entries[0].success


# ---------------------------------------------------------------------------
# Task 2.3: compute_review_summary tests
# ---------------------------------------------------------------------------


class TestComputeReviewSummary:
    def test_no_reviews_returns_none(self):
        phases = [_make_phase(phase="implement")]
        assert compute_review_summary(phases) is None

    def test_single_round(self):
        phases = [
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
        ]
        summary = compute_review_summary(phases)
        assert summary is not None
        assert summary.review_rounds == 1
        assert summary.fix_iterations == 0
        assert summary.per_round_review_counts == [3]

    def test_multiple_rounds_with_fixes(self):
        phases = [
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="fix"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
        ]
        summary = compute_review_summary(phases)
        assert summary is not None
        assert summary.review_rounds == 2
        assert summary.fix_iterations == 1
        assert summary.per_round_review_counts == [2, 3]

    def test_empty_phases(self):
        assert compute_review_summary([]) is None


# ---------------------------------------------------------------------------
# Task 2.4: compute_show_result tests
# ---------------------------------------------------------------------------


class TestComputeShowResult:
    def test_basic_result(self):
        run = _make_run(phases=[_make_phase(phase="plan"), _make_phase(phase="implement")])
        result = compute_show_result(run)
        assert result.header.run_id == "run-20260317_120000-abc123"
        assert len(result.timeline) == 2
        assert result.review_summary is None
        assert not result.has_decision
        assert not result.has_ci_fix

    def test_with_decision(self):
        run = _make_run(phases=[
            _make_phase(phase="review"),
            _make_phase(phase="decision", success=True),
        ])
        result = compute_show_result(run)
        assert result.has_decision
        assert result.decision_success

    def test_with_ci_fix(self):
        run = _make_run(phases=[
            _make_phase(phase="ci_fix", success=False),
            _make_phase(phase="ci_fix", success=True),
        ])
        result = compute_show_result(run)
        assert result.has_ci_fix
        assert result.ci_fix_attempts == 2
        assert result.ci_fix_final_success

    def test_with_review_summary(self):
        run = _make_run(phases=[
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="fix"),
            _make_phase(phase="review"),
        ])
        result = compute_show_result(run)
        assert result.review_summary is not None
        assert result.review_summary.review_rounds == 2

    def test_phase_filter(self):
        run = _make_run(phases=[
            _make_phase(phase="plan"),
            _make_phase(phase="review", model="opus"),
            _make_phase(phase="review", model="sonnet"),
        ])
        result = compute_show_result(run, phase_filter="review")
        assert result.phase_filter == "review"
        assert len(result.phase_detail) == 2
        assert result.phase_detail[0].model == "opus"
        assert result.phase_detail[1].model == "sonnet"

    def test_phase_filter_no_matches(self):
        run = _make_run(phases=[_make_phase(phase="plan")])
        result = compute_show_result(run, phase_filter="review")
        assert result.phase_detail == []


# ---------------------------------------------------------------------------
# Task 3.1: Render smoke tests
# ---------------------------------------------------------------------------


class TestRenderSmoke:
    def test_render_run_header_no_crash(self):
        con = _capture_console()
        header = compute_run_header(_make_run())
        render_run_header(con, header)
        output = _get_output(con)
        assert "run-20260317_120000-abc123" in output
        assert "COMPLETED" in output

    def test_render_run_header_failed_status(self):
        con = _capture_console()
        header = compute_run_header(_make_run(status="failed"))
        render_run_header(con, header)
        output = _get_output(con)
        assert "FAILED" in output

    def test_render_phase_timeline_no_crash(self):
        con = _capture_console()
        entries = collapse_phase_timeline([
            _make_phase(phase="plan"),
            _make_phase(phase="implement"),
        ])
        render_phase_timeline(con, entries)
        output = _get_output(con)
        assert "plan" in output
        assert "implement" in output

    def test_render_phase_timeline_empty(self):
        con = _capture_console()
        render_phase_timeline(con, [])
        assert _get_output(con) == ""

    def test_render_review_summary_no_crash(self):
        con = _capture_console()
        summary = ReviewSummary(review_rounds=2, fix_iterations=1, per_round_review_counts=[3, 2])
        render_review_summary(con, summary)
        output = _get_output(con)
        assert "2" in output
        assert "Review" in output

    def test_render_artifact_links_no_crash(self):
        con = _capture_console()
        header = compute_run_header(_make_run())
        render_artifact_links(con, header)
        output = _get_output(con)
        assert "prd.md" in output
        assert "tasks.md" in output

    def test_render_artifact_links_empty(self):
        con = _capture_console()
        header = compute_run_header(_make_run(prd_rel=None, task_rel=None, branch_name=None))
        render_artifact_links(con, header)
        # No panel should be rendered
        assert _get_output(con) == ""

    def test_render_phase_detail_no_crash(self):
        con = _capture_console()
        entries = [
            PhaseTimelineEntry(
                phase="review", model="opus", duration_ms=30000,
                cost_usd=1.5, success=True, session_id="sess-1",
            ),
        ]
        render_phase_detail(con, entries, "review")
        output = _get_output(con)
        assert "review" in output
        assert "opus" in output

    def test_render_phase_detail_empty(self):
        con = _capture_console()
        render_phase_detail(con, [], "review")
        output = _get_output(con)
        assert "No executions" in output

    def test_render_show_full_no_crash(self):
        con = _capture_console()
        run = _make_run(phases=[
            _make_phase(phase="plan"),
            _make_phase(phase="implement"),
            _make_phase(phase="review"),
            _make_phase(phase="review"),
            _make_phase(phase="decision"),
            _make_phase(phase="deliver"),
        ])
        result = compute_show_result(run)
        render_show(con, result)
        output = _get_output(con)
        assert "Run Details" in output
        assert "Phase Timeline" in output
        assert "Artifacts" in output

    def test_render_show_with_ci_fix(self):
        con = _capture_console()
        run = _make_run(phases=[
            _make_phase(phase="ci_fix", success=False),
            _make_phase(phase="ci_fix", success=True),
        ])
        result = compute_show_result(run)
        render_show(con, result)
        output = _get_output(con)
        assert "CI Fix" in output

    def test_render_show_with_phase_filter(self):
        con = _capture_console()
        run = _make_run(phases=[
            _make_phase(phase="review", model="opus"),
            _make_phase(phase="review", model="sonnet"),
        ])
        result = compute_show_result(run, phase_filter="review")
        render_show(con, result)
        output = _get_output(con)
        assert "Phase Detail" in output
