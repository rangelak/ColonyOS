"""Tests for standalone review: branch validation, diff extraction, prompt building,
parallel execution, artifact saving, and exit code logic."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides) -> ColonyConfig:
    personas = overrides.pop("personas", [
        Persona(role="Engineer", expertise="Backend", perspective="Scale", reviewer=True),
        Persona(role="Security", expertise="AppSec", perspective="Safety", reviewer=True),
    ])
    config = ColonyConfig(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        personas=personas,
        **overrides,
    )
    save_config(tmp_path, config)
    return config


def _approve_result(cost: float = 0.01) -> PhaseResult:
    return PhaseResult(
        phase=Phase.REVIEW,
        success=True,
        cost_usd=cost,
        artifacts={"result": "All good.\n\nVERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks great."},
    )


def _request_changes_result(cost: float = 0.01) -> PhaseResult:
    return PhaseResult(
        phase=Phase.REVIEW,
        success=True,
        cost_usd=cost,
        artifacts={
            "result": (
                "Issues found.\n\nVERDICT: request-changes\n\n"
                "FINDINGS:\n- [src/foo.py]: Missing error handling\n\n"
                "SYNTHESIS:\nNeeds work."
            )
        },
    )


def _fix_result(cost: float = 0.02) -> PhaseResult:
    return PhaseResult(
        phase=Phase.FIX,
        success=True,
        cost_usd=cost,
        artifacts={"result": "Fixed all issues."},
    )


def _decision_go_result(cost: float = 0.01) -> PhaseResult:
    return PhaseResult(
        phase=Phase.DECISION,
        success=True,
        cost_usd=cost,
        artifacts={"result": "VERDICT: GO\n\n### Rationale\nAll clear."},
    )


def _decision_nogo_result(cost: float = 0.01) -> PhaseResult:
    return PhaseResult(
        phase=Phase.DECISION,
        success=True,
        cost_usd=cost,
        artifacts={"result": "VERDICT: NO-GO\n\n### Rationale\nCritical issues."},
    )


# ---------------------------------------------------------------------------
# 1. Branch validation
# ---------------------------------------------------------------------------


class TestValidateBranchExists:
    def test_existing_branch(self, tmp_path: Path):
        from colonyos.orchestrator import validate_branch_exists

        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="  my-branch\n")
            ok, err = validate_branch_exists("my-branch", tmp_path)

        assert ok is True
        assert err == ""
        mock_run.assert_called_once_with(
            ["git", "branch", "--list", "--", "my-branch"],
            capture_output=True, text=True, cwd=tmp_path,
        )

    def test_missing_branch(self, tmp_path: Path):
        from colonyos.orchestrator import validate_branch_exists

        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            ok, err = validate_branch_exists("no-such-branch", tmp_path)

        assert ok is False
        assert "not found locally" in err
        assert "git fetch" in err

    def test_remote_ref_rejected(self, tmp_path: Path):
        from colonyos.orchestrator import validate_branch_exists

        ok, err = validate_branch_exists("origin/feature", tmp_path)
        assert ok is False
        assert "Remote-style ref" in err
        assert "git checkout feature" in err

    def test_upstream_ref_rejected(self, tmp_path: Path):
        from colonyos.orchestrator import validate_branch_exists

        ok, err = validate_branch_exists("upstream/main", tmp_path)
        assert ok is False
        assert "Remote-style ref" in err

    def test_branch_with_slash_not_remote(self, tmp_path: Path):
        """Branches like feature/foo should NOT be rejected."""
        from colonyos.orchestrator import validate_branch_exists

        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="  feature/foo\n")
            ok, err = validate_branch_exists("feature/foo", tmp_path)

        assert ok is True


# ---------------------------------------------------------------------------
# 2. Diff extraction
# ---------------------------------------------------------------------------


class TestGetBranchDiff:
    def test_normal_diff(self, tmp_path: Path):
        from colonyos.orchestrator import _get_branch_diff

        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="diff --git a/f.py b/f.py\n+hello")
            diff = _get_branch_diff("main", "feature", tmp_path)

        assert "diff --git" in diff
        mock_run.assert_called_once_with(
            ["git", "diff", "main...feature"],
            capture_output=True, text=True, cwd=tmp_path,
        )

    def test_truncation(self, tmp_path: Path):
        from colonyos.orchestrator import _get_branch_diff

        big_diff = "x" * 20_000
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=big_diff)
            diff = _get_branch_diff("main", "feature", tmp_path, max_chars=100)

        assert len(diff.split("\n")[0]) <= 100
        assert "truncated" in diff

    def test_empty_diff(self, tmp_path: Path):
        from colonyos.orchestrator import _get_branch_diff

        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            diff = _get_branch_diff("main", "feature", tmp_path)

        assert diff == ""

    def test_subprocess_error(self, tmp_path: Path):
        from colonyos.orchestrator import _get_branch_diff

        with patch("colonyos.orchestrator.subprocess.run", side_effect=OSError("fail")):
            diff = _get_branch_diff("main", "feature", tmp_path)

        assert diff == ""


# ---------------------------------------------------------------------------
# 3. Prompt builders
# ---------------------------------------------------------------------------


class TestBuildStandaloneReviewPrompt:
    def test_contains_persona_identity(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_review_prompt

        config = _make_config(tmp_path)
        persona = config.personas[0]
        system, user = _build_standalone_review_prompt(
            persona, config, "feat-branch", "main", "some diff",
        )

        assert persona.role in system
        assert persona.expertise in system
        assert persona.perspective in system

    def test_contains_diff(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_review_prompt

        config = _make_config(tmp_path)
        persona = config.personas[0]
        system, user = _build_standalone_review_prompt(
            persona, config, "feat-branch", "main", "diff --git a/f.py",
        )

        assert "diff --git a/f.py" in system

    def test_references_branch_and_base(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_review_prompt

        config = _make_config(tmp_path)
        persona = config.personas[0]
        system, user = _build_standalone_review_prompt(
            persona, config, "feat-branch", "develop", "diff",
        )

        assert "feat-branch" in user
        assert "develop" in user

    def test_no_prd_path(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_review_prompt

        config = _make_config(tmp_path)
        persona = config.personas[0]
        system, user = _build_standalone_review_prompt(
            persona, config, "feat-branch", "main", "diff",
        )

        assert "prd_path" not in system
        assert "prd_path" not in user


class TestBuildStandaloneFixPrompt:
    def test_contains_findings(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_fix_prompt

        config = _make_config(tmp_path)
        system, user = _build_standalone_fix_prompt(
            config, "feat-branch", "Missing error handling", 1,
        )

        assert "Missing error handling" in system

    def test_contains_iteration(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_fix_prompt

        config = _make_config(tmp_path)
        system, user = _build_standalone_fix_prompt(
            config, "feat-branch", "findings", 2,
        )

        assert "2" in user

    def test_no_prd_or_task_paths(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_fix_prompt

        config = _make_config(tmp_path)
        system, user = _build_standalone_fix_prompt(
            config, "feat-branch", "findings", 1,
        )

        assert "prd_path" not in system
        assert "task_path" not in system


class TestBuildStandaloneDecisionPrompt:
    def test_contains_branch_and_base(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_decision_prompt

        config = _make_config(tmp_path)
        system, user = _build_standalone_decision_prompt(config, "feat-branch", "main")

        assert "feat-branch" in system
        assert "main" in system

    def test_no_prd_reference(self, tmp_path: Path):
        from colonyos.orchestrator import _build_standalone_decision_prompt

        config = _make_config(tmp_path)
        system, user = _build_standalone_decision_prompt(config, "feat-branch", "main")

        assert "prd_path" not in system


# ---------------------------------------------------------------------------
# 4. run_standalone_review() orchestration
# ---------------------------------------------------------------------------


class TestRunStandaloneReview:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="some diff")
    def test_all_approve_first_round(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        all_approved, results, cost, verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        assert all_approved is True
        assert verdict is None  # no --decide flag
        assert len(results) == 2
        assert cost > 0
        # Check artifacts saved
        reviews_dir = tmp_path / config.reviews_dir
        assert reviews_dir.exists()
        summary = list(reviews_dir.glob("**/*_summary_*.md"))
        assert len(summary) == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_request_changes_triggers_fix(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        # Round 1: one requests changes
        # Round 2: all approve
        mock_parallel.side_effect = [
            [_approve_result(), _request_changes_result()],
            [_approve_result(), _approve_result()],
        ]
        mock_phase.return_value = _fix_result()

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        assert all_approved is True
        assert mock_phase.called  # fix was called
        assert mock_parallel.call_count == 2  # two review rounds

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_no_fix_skips_fix_loop(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _request_changes_result()]

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, no_fix=True,
        )

        assert all_approved is False
        assert mock_parallel.call_count == 1  # only one round

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_budget_exhaustion_stops_early(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(
            tmp_path,
            budget=BudgetConfig(per_phase=0.05, per_run=0.10),
        )
        # First round costs 0.10 total, exhausting the per_run budget
        mock_parallel.return_value = [_request_changes_result(cost=0.05), _request_changes_result(cost=0.05)]

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        # Should stop after first round due to budget (remaining 0.0 < per_phase 0.05)
        assert mock_parallel.call_count == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_decide_runs_decision_gate(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]
        mock_phase.return_value = _decision_go_result()

        all_approved, results, cost, verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, decide=True,
        )

        assert all_approved is True
        assert verdict == "GO"
        assert mock_phase.called
        # Decision artifact saved
        reviews_dir = tmp_path / config.reviews_dir
        decision_files = list(reviews_dir.glob("**/*_decision_standalone_*.md"))
        assert len(decision_files) == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_decide_nogo_returns_false(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]
        mock_phase.return_value = _decision_nogo_result()

        all_approved, results, cost, verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, decide=True,
        )

        assert all_approved is False
        assert verdict == "NO-GO"

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_summary_artifact_content(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        run_standalone_review("feat", "main", tmp_path, config, quiet=True)

        reviews_dir = tmp_path / config.reviews_dir
        summary = list(reviews_dir.glob("**/*_summary_*.md"))[0]
        content = summary.read_text()
        assert "Engineer" in content
        assert "Security" in content
        assert "Total cost" in content

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_no_reviewers_returns_early(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path, personas=[
            Persona(role="PM", expertise="Product", perspective="User", reviewer=False),
        ])

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        assert all_approved is True
        assert results == []
        assert cost == 0.0
        mock_parallel.assert_not_called()

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="")
    def test_empty_diff_still_runs(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        assert all_approved is True
        assert mock_parallel.call_count == 1


class TestParallelExecution:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_correct_number_of_calls(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        run_standalone_review("feat", "main", tmp_path, config, quiet=True)

        # Should have been called with a list of 2 review specs
        assert mock_parallel.call_count == 1
        calls_arg = mock_parallel.call_args[0][0]
        assert len(calls_arg) == 2

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_call_specs_have_correct_fields(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        run_standalone_review("feat", "main", tmp_path, config, quiet=True)

        calls_arg = mock_parallel.call_args[0][0]
        for spec in calls_arg:
            assert spec["phase"] == Phase.REVIEW
            assert spec["allowed_tools"] == ["Read", "Glob", "Grep", "Bash"]
            assert spec["model"] == config.model
            assert spec["budget_usd"] == config.budget.per_phase


# ---------------------------------------------------------------------------
# 5. Review artifact filenames
# ---------------------------------------------------------------------------


class TestArtifactFilenames:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_review_artifact_filenames(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        run_standalone_review("feature/my-thing", "main", tmp_path, config, quiet=True)

        reviews_dir = tmp_path / config.reviews_dir
        all_files = sorted(f.name for f in reviews_dir.glob("**/*.md"))
        # Should have: 2 review files + 1 summary
        review_files = [f for f in all_files if "round1" in f]
        summary_files = [f for f in all_files if "summary" in f]
        assert len(review_files) == 2
        assert len(summary_files) == 1
        # Feature slug present in filenames
        assert "feature_my_thing" in review_files[0]
        assert "round1" in review_files[0]


# ---------------------------------------------------------------------------
# 6. _print_review_summary
# ---------------------------------------------------------------------------


class TestPrintReviewSummary:
    def test_prints_verdicts(self):
        from colonyos.cli import _print_review_summary

        personas = [
            Persona(role="Eng", expertise="x", perspective="y", reviewer=True),
            Persona(role="Sec", expertise="x", perspective="y", reviewer=True),
        ]
        results = [_approve_result(), _request_changes_result()]
        from unittest.mock import patch as p
        from click.testing import CliRunner

        runner = CliRunner()
        with runner.isolated_filesystem():
            from io import StringIO
            output = StringIO()
            with p("click.echo", side_effect=lambda msg="", **kw: output.write(msg + "\n")):
                _print_review_summary(results, personas, 0.05)

            text = output.getvalue()
            assert "approve" in text
            assert "request-changes" in text
            assert "0.0500" in text

    def test_prints_decision(self):
        from colonyos.cli import _print_review_summary

        personas = [
            Persona(role="Eng", expertise="x", perspective="y", reviewer=True),
        ]
        results = [_approve_result()]
        from io import StringIO
        from unittest.mock import patch as p

        output = StringIO()
        with p("click.echo", side_effect=lambda msg="", **kw: output.write(msg + "\n")):
            _print_review_summary(results, personas, 0.01, decision_verdict="GO")

        assert "GO" in output.getvalue()


# ---------------------------------------------------------------------------
# 7. CLI review command
# ---------------------------------------------------------------------------


class TestReviewCLI:
    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    def test_no_config_shows_init_error(self, runner, tmp_path: Path):
        from colonyos.cli import app

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["review", "my-branch"])

        assert result.exit_code != 0
        assert "colonyos init" in result.output

    def test_invalid_branch_shows_error(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(False, "Branch 'bad' not found locally. Try: git fetch && git checkout bad")):
            result = runner.invoke(app, ["review", "bad"])

        assert result.exit_code != 0
        assert "not found" in result.output

    def test_invalid_base_shows_error(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        def mock_validate(branch, repo_root):
            if branch == "feat":
                return True, ""
            return False, f"Branch '{branch}' not found locally."

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", side_effect=mock_validate):
            result = runner.invoke(app, ["review", "feat", "--base", "nonexistent"])

        assert result.exit_code != 0
        assert "not found" in result.output

    def test_successful_review_exits_0(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [_approve_result(), _approve_result()], 0.02, None)):
            result = runner.invoke(app, ["review", "feat"])

        assert result.exit_code == 0

    def test_failed_review_exits_1(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(False, [_request_changes_result()], 0.01, None)):
            result = runner.invoke(app, ["review", "feat"])

        assert result.exit_code == 1

    def test_no_fix_flag_passed_through(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [], 0.0, None)) as mock_review:
            runner.invoke(app, ["review", "feat", "--no-fix"])

        assert mock_review.call_args[1]["no_fix"] is True

    def test_base_flag_passed_through(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [], 0.0, None)) as mock_review:
            runner.invoke(app, ["review", "feat", "--base", "develop"])

        assert mock_review.call_args[0][1] == "develop"

    def test_decide_flag_passed_through(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [], 0.0, None)) as mock_review:
            runner.invoke(app, ["review", "feat", "--decide"])

        assert mock_review.call_args[1]["decide"] is True

    def test_verbose_flag(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [], 0.0, None)) as mock_review:
            runner.invoke(app, ["review", "feat", "-v"])

        assert mock_review.call_args[1]["verbose"] is True

    def test_quiet_flag(self, runner, tmp_path: Path):
        from colonyos.cli import app

        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")), \
             patch("colonyos.cli.run_standalone_review", return_value=(True, [], 0.0, None)) as mock_review:
            runner.invoke(app, ["review", "feat", "-q"])

        assert mock_review.call_args[1]["quiet"] is True

    def test_no_reviewers_shows_error(self, runner, tmp_path: Path):
        from colonyos.cli import app

        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[Persona(role="PM", expertise="Product", perspective="User", reviewer=False)],
        )
        save_config(tmp_path, config)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.validate_branch_exists", return_value=(True, "")):
            result = runner.invoke(app, ["review", "feat"])

        assert result.exit_code != 0
        assert "No reviewer personas" in result.output


# ---------------------------------------------------------------------------
# 8. Exit code logic (integration-level)
# ---------------------------------------------------------------------------


class TestExitCodeLogic:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_0_all_approve_first_round(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )
        assert all_approved is True

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_0_approve_after_fix(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.side_effect = [
            [_approve_result(), _request_changes_result()],
            [_approve_result(), _approve_result()],
        ]
        mock_phase.return_value = _fix_result()

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )
        assert all_approved is True

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_1_no_fix(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _request_changes_result()]

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, no_fix=True,
        )
        assert all_approved is False

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_1_fix_loop_exhausted(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path, max_fix_iterations=1)
        # Both rounds: changes requested
        mock_parallel.side_effect = [
            [_request_changes_result(), _request_changes_result()],
            [_request_changes_result(), _request_changes_result()],
        ]
        mock_phase.return_value = _fix_result()

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )
        assert all_approved is False

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_0_decision_go(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]
        mock_phase.return_value = _decision_go_result()

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, decide=True,
        )
        assert all_approved is True

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_exit_1_decision_nogo(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_approve_result(), _approve_result()]
        mock_phase.return_value = _decision_nogo_result()

        all_approved, _, _, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True, decide=True,
        )
        assert all_approved is False


# ---------------------------------------------------------------------------
# 9. Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_budget_stops_mid_loop(self, mock_diff, mock_parallel, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(
            tmp_path,
            budget=BudgetConfig(per_phase=0.05, per_run=0.10),
            max_fix_iterations=3,
        )
        # Each review round costs 0.10 total, exhausting per_run budget
        mock_parallel.return_value = [
            _request_changes_result(cost=0.05),
            _request_changes_result(cost=0.05),
        ]

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        # Should stop after 1 round because remaining (0.0) < per_phase (0.05)
        assert mock_parallel.call_count == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_cost_tracking_across_phases(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.side_effect = [
            [_approve_result(cost=0.10), _request_changes_result(cost=0.10)],
            [_approve_result(cost=0.10), _approve_result(cost=0.10)],
        ]
        mock_phase.return_value = _fix_result(cost=0.05)

        _, _, cost, _ = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        # 0.10*2 (round1) + 0.05 (fix) + 0.10*2 (round2) = 0.45
        assert abs(cost - 0.45) < 0.001


# ---------------------------------------------------------------------------
# 10. Edge case: fix phase failure
# ---------------------------------------------------------------------------


class TestFixPhaseFailure:
    @patch("colonyos.orchestrator.run_phase_sync")
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator._get_branch_diff", return_value="diff")
    def test_fix_failure_stops_gracefully(self, mock_diff, mock_parallel, mock_phase, tmp_path: Path):
        from colonyos.orchestrator import run_standalone_review

        config = _make_config(tmp_path)
        mock_parallel.return_value = [_request_changes_result(), _request_changes_result()]
        mock_phase.return_value = PhaseResult(
            phase=Phase.FIX, success=False, cost_usd=0.01, error="Agent crash",
        )

        all_approved, results, cost, _verdict = run_standalone_review(
            "feat", "main", tmp_path, config, quiet=True,
        )

        assert all_approved is False
        assert mock_parallel.call_count == 1  # no second review round
