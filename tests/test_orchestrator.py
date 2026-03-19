import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import click
import pytest

from colonyos.config import ColonyConfig, BudgetConfig, LearningsConfig, PhasesConfig, save_config
from colonyos.learnings import learnings_path, LearningEntry, append_learnings
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, ResumeState, RunLog, RunStatus
from colonyos.orchestrator import (
    run,
    prepare_resume,
    _extract_pr_number_from_log,
    _format_personas_block,
    _build_persona_agents,
    _build_ci_fix_prompt,
    _build_implement_prompt,
    _build_fix_prompt,
    _build_learn_prompt,
    _build_plan_prompt,
    _build_deliver_prompt,
    _build_ceo_prompt,
    _build_run_id,
    _load_run_log,
    _parse_learn_output,
    _parse_parent_tasks,
    _persona_slug,
    _run_ci_fix_loop,
    reviewer_personas,
    _build_persona_review_prompt,
    extract_review_verdict,
    _collect_review_findings,
    _save_review_artifact,
    _save_run_log,
    _validate_resume_preconditions,
    _compute_next_phase,
    _SKIP_MAP,
)


REVIEWER_PERSONA = Persona(
    role="Engineer", expertise="Backend", perspective="Scale", reviewer=True
)
NON_REVIEWER_PERSONA = Persona(
    role="Designer", expertise="UX", perspective="Usability", reviewer=False
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "cOS_prds").mkdir()
    (tmp_path / "cOS_tasks").mkdir()
    (tmp_path / "cOS_reviews").mkdir()
    (tmp_path / ".colonyos").mkdir()
    # Initialize a git repo so preflight checks can run
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    # Ignore colonyos working dirs so save_config doesn't dirty the tree
    (tmp_path / ".gitignore").write_text(".colonyos/\ncOS_prds/\ncOS_tasks/\ncOS_reviews/\ncOS_runs/\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


@pytest.fixture
def config() -> ColonyConfig:
    return ColonyConfig(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        personas=[REVIEWER_PERSONA],
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=10.0),
        phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True),
    )


def _fake_phase_result(phase: Phase, success: bool = True) -> PhaseResult:
    return PhaseResult(
        phase=phase,
        success=success,
        cost_usd=0.01,
        duration_ms=100,
        session_id="test-session",
        artifacts={"result": "done"},
    )


def _approve_review_result() -> PhaseResult:
    return PhaseResult(
        phase=Phase.REVIEW,
        success=True,
        cost_usd=0.01,
        duration_ms=100,
        session_id="test-session",
        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."},
    )


def _request_changes_review_result() -> PhaseResult:
    return PhaseResult(
        phase=Phase.REVIEW,
        success=True,
        cost_usd=0.01,
        duration_ms=100,
        session_id="test-session",
        artifacts={"result": "VERDICT: request-changes\n\nFINDINGS:\n- src/foo.py: Missing tests\n\nSYNTHESIS:\nNeeds work."},
    )


class TestPhaseReviewEnum:
    def test_review_exists(self):
        assert Phase.REVIEW == "review"
        assert Phase.REVIEW.value == "review"

    def test_phase_ordering(self):
        phases = list(Phase)
        assert phases == [Phase.CEO, Phase.PLAN, Phase.TRIAGE, Phase.IMPLEMENT, Phase.REVIEW, Phase.DECISION, Phase.FIX, Phase.LEARN, Phase.DELIVER, Phase.CI_FIX]

    def test_fix_phase_exists(self):
        assert Phase.FIX == "fix"
        assert Phase.FIX.value == "fix"


class TestFormatPersonasBlock:
    def test_with_personas(self):
        personas = [
            Persona(role="Engineer", expertise="APIs", perspective="Scale")
        ]
        block = _format_personas_block(personas)
        assert "engineer" in block
        assert "subagent" in block.lower()

    def test_without_personas(self):
        block = _format_personas_block([])
        assert "senior engineer" in block

    def test_lists_subagent_keys(self):
        personas = [
            Persona(role="Steve Jobs", expertise="Product", perspective="Simplify"),
            Persona(role="Linus Torvalds", expertise="Kernel", perspective="Correctness"),
        ]
        block = _format_personas_block(personas)
        assert "`steve_jobs`" in block
        assert "`linus_torvalds`" in block


class TestBuildPersonaAgents:
    def test_builds_agents_per_persona(self):
        personas = [
            Persona(role="Steve Jobs", expertise="Product vision", perspective="Simplify"),
            Persona(role="Linus Torvalds", expertise="Kernel", perspective="Correctness"),
        ]
        agents = _build_persona_agents(personas)
        assert "steve_jobs" in agents
        assert "linus_torvalds" in agents
        assert agents["steve_jobs"].description.startswith("Steve Jobs")
        assert "Read" in agents["linus_torvalds"].tools

    def test_empty_personas(self):
        agents = _build_persona_agents([])
        assert agents == {}


class TestReviewerPersonas:
    def test_filters_to_reviewers(self):
        config = ColonyConfig(
            personas=[REVIEWER_PERSONA, NON_REVIEWER_PERSONA],
        )
        reviewers = reviewer_personas(config)
        assert len(reviewers) == 1
        assert reviewers[0].role == "Engineer"

    def test_no_reviewers(self):
        config = ColonyConfig(
            personas=[NON_REVIEWER_PERSONA],
        )
        assert reviewer_personas(config) == []

    def test_all_reviewers(self):
        p1 = Persona(role="A", expertise="a", perspective="a", reviewer=True)
        p2 = Persona(role="B", expertise="b", perspective="b", reviewer=True)
        config = ColonyConfig(personas=[p1, p2])
        assert len(reviewer_personas(config)) == 2


class TestBuildPersonaReviewPrompt:
    def test_contains_persona_identity(self):
        persona = Persona(role="Security Lead", expertise="AppSec", perspective="Threat model", reviewer=True)
        config = ColonyConfig()
        system, user = _build_persona_review_prompt(persona, config, "prd.md", "feat/x")
        assert "Security Lead" in system
        assert "AppSec" in system
        assert "Threat model" in system

    def test_contains_branch_and_prd(self):
        config = ColonyConfig()
        system, user = _build_persona_review_prompt(REVIEWER_PERSONA, config, "cOS_prds/test.md", "feat/test")
        assert "cOS_prds/test.md" in system
        assert "feat/test" in system
        assert "feat/test" in user

    def test_review_tools_not_in_prompt(self):
        config = ColonyConfig()
        system, _ = _build_persona_review_prompt(REVIEWER_PERSONA, config, "prd.md", "branch")
        assert "Agent" not in system


class TestExtractReviewVerdict:
    def test_approve(self):
        assert extract_review_verdict("VERDICT: approve\nLooks good.") == "approve"

    def test_request_changes(self):
        assert extract_review_verdict("VERDICT: request-changes\nNeeds fixes.") == "request-changes"

    def test_case_insensitive(self):
        assert extract_review_verdict("Verdict: Approve") == "approve"

    def test_defaults_to_request_changes(self):
        assert extract_review_verdict("No clear verdict.") == "request-changes"


class TestCollectReviewFindings:
    def test_collects_request_changes(self):
        results = [_request_changes_review_result(), _approve_review_result()]
        reviewers = [REVIEWER_PERSONA, Persona(role="Other", expertise="X", perspective="Y", reviewer=True)]
        findings = _collect_review_findings(results, reviewers)
        assert len(findings) == 1
        assert findings[0][0] == "Engineer"

    def test_all_approve_returns_empty(self):
        results = [_approve_review_result()]
        reviewers = [REVIEWER_PERSONA]
        findings = _collect_review_findings(results, reviewers)
        assert findings == []

    def test_all_request_changes(self):
        r1 = Persona(role="A", expertise="a", perspective="a", reviewer=True)
        r2 = Persona(role="B", expertise="b", perspective="b", reviewer=True)
        results = [_request_changes_review_result(), _request_changes_review_result()]
        findings = _collect_review_findings(results, [r1, r2])
        assert len(findings) == 2


class TestParseParentTasks:
    def test_parses_unchecked_tasks(self):
        content = """## Tasks

- [ ] 1.0 Update models
  - [ ] 1.1 Add field
- [ ] 2.0 Update config
  - [ ] 2.1 Add default
"""
        tasks = _parse_parent_tasks(content)
        assert len(tasks) == 2
        assert "1.0 Update models" in tasks[0]
        assert "2.0 Update config" in tasks[1]

    def test_parses_checked_tasks(self):
        content = "- [x] 1.0 Done task\n- [ ] 2.0 Pending task\n"
        tasks = _parse_parent_tasks(content)
        assert len(tasks) == 2

    def test_ignores_subtasks(self):
        content = "- [ ] 1.0 Parent\n  - [ ] 1.1 Child\n"
        tasks = _parse_parent_tasks(content)
        assert len(tasks) == 1
        assert "1.0 Parent" in tasks[0]

    def test_empty_content(self):
        assert _parse_parent_tasks("") == []


class TestPersonaSlug:
    def test_basic(self):
        assert _persona_slug("Steve Jobs") == "steve_jobs"

    def test_complex_role(self):
        assert _persona_slug("YC Partner (Michael Seibel)") == "yc_partner_michael_seibel"


class TestBuildRunId:
    def test_format(self):
        rid = _build_run_id("test prompt")
        assert rid.startswith("run-")
        assert len(rid) > 20


class TestRun:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_run_success_with_review(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 5
        assert mock_parallel.call_count == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_phase_skipped_when_disabled(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        config.phases.review = False
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert len(log.phases) == 4
        assert mock_run.call_count == 4
        phase_types = [p.phase for p in log.phases]
        assert Phase.REVIEW not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_skipped_when_noreviewer_personas(self, mock_run, tmp_repo: Path):
        """No reviewer personas means review phase is skipped entirely."""
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[NON_REVIEWER_PERSONA],
            model="test-model",
            budget=BudgetConfig(per_phase=1.0, per_run=10.0),
            phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True),
        )
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 4

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_saves_artifacts(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add tests", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        assert reviews_dir.exists()
        review_files = list(reviews_dir.glob("**/*.md"))
        assert len(review_files) >= 2  # 1 persona review + 1 decision

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_uses_parallel_runner(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Reviews use run_phases_parallel_sync, not run_phase_sync."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add tests", repo_root=tmp_repo, config=config)

        assert mock_parallel.call_count == 1
        calls = mock_parallel.call_args_list[0]
        review_calls = calls[0][0]
        assert len(review_calls) == 1  # 1 reviewer persona
        assert review_calls[0]["phase"] == Phase.REVIEW
        assert review_calls[0]["allowed_tools"] == ["Read", "Glob", "Grep", "Bash"]

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_multiplereviewer_personas(self, mock_run, mock_parallel, tmp_repo: Path):
        """All reviewer personas get their own parallel session."""
        r1 = Persona(role="Systems Eng", expertise="Distributed", perspective="Reliability", reviewer=True)
        r2 = Persona(role="Security Eng", expertise="AppSec", perspective="Threats", reviewer=True)
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[r1, r2, NON_REVIEWER_PERSONA],
            model="test-model",
            budget=BudgetConfig(per_phase=1.0, per_run=10.0),
            phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True),
        )
        save_config(tmp_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result(), _approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        review_calls = mock_parallel.call_args_list[0][0][0]
        assert len(review_calls) == 2  # Only 2 reviewer personas (not the designer)

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_plan_passes_persona_agents(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.return_value = _fake_phase_result(Phase.PLAN)

        run("Add tests", repo_root=tmp_repo, config=config, plan_only=True)

        call_kwargs = mock_run.call_args_list[0]
        assert call_kwargs.kwargs.get("agents") is not None
        assert "engineer" in call_kwargs.kwargs["agents"]

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_plan_only(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.return_value = _fake_phase_result(Phase.PLAN)

        log = run("Add tests", repo_root=tmp_repo, config=config, plan_only=True)

        assert log.status == RunStatus.COMPLETED
        assert len(log.phases) == 1
        assert mock_run.call_count == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_plan_failure_stops_run(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.return_value = _fake_phase_result(Phase.PLAN, success=False)

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        assert len(log.phases) == 1
        assert mock_run.call_count == 1

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_from_prd_skips_plan(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        prd = tmp_repo / "cOS_prds" / "20260316_120000_prd_test.md"
        prd.write_text("# PRD", encoding="utf-8")

        mock_run.side_effect = [
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run(
            "Implement test",
            repo_root=tmp_repo,
            config=config,
            from_prd=str(prd),
        )

        assert log.status == RunStatus.COMPLETED

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_run_log_saved(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        runs_dir = tmp_repo / ".colonyos" / "runs"
        assert runs_dir.exists()
        log_files = list(runs_dir.glob("*.json"))
        assert len(log_files) == 1

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_decision_nogo_stops_pipeline(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Decision gate NO-GO verdict prevents delivery."""
        config.max_fix_iterations = 0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: NO-GO\n\nToo many issues."}),
            _fake_phase_result(Phase.LEARN),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types
        assert Phase.DECISION in phase_types


class TestBuildFixPrompt:
    def test_returns_tuple(self):
        config = ColonyConfig(max_fix_iterations=2)
        result = _build_fix_prompt(
            config, "prd.md", "tasks.md", "feat/branch",
            "### Engineer\n\nVERDICT: request-changes\nMissing tests", 1,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_contains_base_and_fix(self):
        config = ColonyConfig(max_fix_iterations=2)
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "feat/branch",
            "Findings here", 1,
        )
        assert "Fix Phase" in system
        assert "fix iteration 1 of 2" in system.lower()

    def test_system_embeds_findings_text(self):
        config = ColonyConfig(max_fix_iterations=3)
        findings = "### Engineer\n\nVERDICT: request-changes\nMissing tests for auth module"
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", findings, 2,
        )
        assert "Missing tests for auth module" in system

    def test_user_prompt_contains_context(self):
        config = ColonyConfig(max_fix_iterations=2)
        _, user = _build_fix_prompt(
            config, "cOS_prds/prd.md", "cOS_tasks/tasks.md",
            "feat/fix", "findings text", 1,
        )
        assert "feat/fix" in user
        assert "cOS_prds/prd.md" in user
        assert "iteration 1" in user

    def test_includes_reviews_dir(self):
        config = ColonyConfig(reviews_dir="my_reviews", max_fix_iterations=2)
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", "text", 1,
        )
        assert "my_reviews" in system

    def test_fix_identity_is_staff_engineer(self):
        config = ColonyConfig(max_fix_iterations=2)
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", "text", 1,
        )
        assert "Staff+" in system
        assert "Google" in system


class TestFixLoop:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_request_changes_triggers_fix(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """request-changes -> fix -> approve -> decision GO -> deliver."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.FIX),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.side_effect = [
            [_request_changes_review_result()],  # round 1: request changes
            [_approve_review_result()],           # round 2: approve
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_max_iterations_exhausted(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """request-changes every round -> decision NO-GO -> fail."""
        config.max_fix_iterations = 2
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.FIX),       # fix 1
            _fake_phase_result(Phase.FIX),       # fix 2
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nStill bad."}),
            _fake_phase_result(Phase.LEARN),
        ]
        mock_parallel.side_effect = [
            [_request_changes_review_result()],  # round 1
            [_request_changes_review_result()],  # round 2 (after fix 1)
            [_request_changes_review_result()],  # round 3 (after fix 2, last round)
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types
        assert phase_types.count(Phase.FIX) == 2

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_zero_max_iterations_no_fix(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """max_fix_iterations=0: only 1 review round, no fix, then decision."""
        config.max_fix_iterations = 0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            _fake_phase_result(Phase.LEARN),
        ]
        mock_parallel.return_value = [_request_changes_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX not in phase_types
        assert Phase.DELIVER not in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_fix_phases_in_runlog(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Fix iterations appear as Phase.FIX in the run log."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.FIX),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.side_effect = [
            [_request_changes_review_result()],
            [_approve_review_result()],
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        fix_phases = [p for p in log.phases if p.phase == Phase.FIX]
        assert len(fix_phases) == 1
        assert fix_phases[0].success is True

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_unknown_verdict_proceeds_to_deliver(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """UNKNOWN decision verdict proceeds to deliver (with warning)."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "No clear verdict here."}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX not in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_fix_phase_failure_stops_loop(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Fix phase failure breaks the loop and proceeds to decision."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.FIX, success=False),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            _fake_phase_result(Phase.LEARN),
        ]
        mock_parallel.return_value = [_request_changes_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_budget_exhaustion_stops_review_loop(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Review loop stops when remaining per-run budget is insufficient."""
        config.budget = BudgetConfig(per_phase=1.0, per_run=2.5)
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            PhaseResult(phase=Phase.PLAN, success=True, cost_usd=1.0,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=1.0,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            # Budget: 2.5 - 2.0 = 0.5 remaining < per_phase(1.0) -> skip reviews
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        # Budget guard should have prevented at least some review rounds
        assert log.status == RunStatus.COMPLETED

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_artifacts_per_persona_per_round(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Each reviewer persona gets a separate artifact file per round."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add feature", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        filenames = {f.name for f in reviews_dir.glob("**/*.md")}
        assert any("round1_" in f for f in filenames)
        # Verify persona subdirectory was created
        persona_dirs = [d.name for d in (reviews_dir / "reviews").iterdir() if d.is_dir()]
        assert any("engineer" in d for d in persona_dirs)


class TestRunLogResumeFields:
    """Task 1: RunLog can hold branch_name, prd_rel, task_rel."""

    def test_defaults_to_none(self):
        log = RunLog(run_id="r1", prompt="test", status=RunStatus.RUNNING)
        assert log.branch_name is None
        assert log.prd_rel is None
        assert log.task_rel is None

    def test_accepts_values(self):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.RUNNING,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        assert log.branch_name == "feat/x"
        assert log.prd_rel == "cOS_prds/prd.md"
        assert log.task_rel == "cOS_tasks/tasks.md"


class TestSaveRunLogResumeFields:
    """Task 2: save_run_log persists resume fields and last_successful_phase."""

    def test_persists_resume_fields(self, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.COMPLETED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        path = _save_run_log(tmp_repo, log)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["branch_name"] == "feat/x"
        assert data["prd_rel"] == "cOS_prds/prd.md"
        assert data["task_rel"] == "cOS_tasks/tasks.md"

    def test_persists_last_successful_phase(self, tmp_repo: Path):
        log = RunLog(
            run_id="r2", prompt="test", status=RunStatus.FAILED,
            phases=[
                _fake_phase_result(Phase.PLAN),
                _fake_phase_result(Phase.IMPLEMENT),
                _fake_phase_result(Phase.REVIEW, success=False),
            ],
        )
        path = _save_run_log(tmp_repo, log)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["last_successful_phase"] == "implement"

    def test_last_successful_phase_none_when_no_success(self, tmp_repo: Path):
        log = RunLog(
            run_id="r3", prompt="test", status=RunStatus.FAILED,
            phases=[_fake_phase_result(Phase.PLAN, success=False)],
        )
        path = _save_run_log(tmp_repo, log)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["last_successful_phase"] is None


class TestLoadRunLog:
    """Task 3.1: _load_run_log tests."""

    def test_loads_valid_json(self, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
            phases=[_fake_phase_result(Phase.PLAN)],
        )
        _save_run_log(tmp_repo, log)
        loaded = _load_run_log(tmp_repo, "r1")
        assert loaded.run_id == "r1"
        assert loaded.status == RunStatus.FAILED
        assert loaded.branch_name == "feat/x"
        assert len(loaded.phases) == 1
        assert loaded.phases[0].phase == Phase.PLAN

    def test_missing_file_raises(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="Run log not found"):
            _load_run_log(tmp_repo, "nonexistent-id")

    def test_corrupted_json_raises(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "bad.json").write_text("{invalid json", encoding="utf-8")
        with pytest.raises(click.ClickException, match="Corrupted run log"):
            _load_run_log(tmp_repo, "bad")

    def test_old_log_without_resume_fields(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "old.json").write_text(json.dumps({
            "run_id": "old", "prompt": "test", "status": "failed",
            "phases": [], "total_cost_usd": 0.0,
        }), encoding="utf-8")
        loaded = _load_run_log(tmp_repo, "old")
        assert loaded.branch_name is None
        assert loaded.prd_rel is None
        assert loaded.task_rel is None


class TestValidateResumePreconditions:
    """Task 3.2: _validate_resume_preconditions tests."""

    def test_fails_on_running_status(self, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.RUNNING,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        with pytest.raises(click.ClickException, match="Only failed runs"):
            _validate_resume_preconditions(tmp_repo, log)

    def test_fails_on_completed_status(self, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.COMPLETED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        with pytest.raises(click.ClickException, match="Only failed runs"):
            _validate_resume_preconditions(tmp_repo, log)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_fails_on_missing_branch(self, mock_subprocess, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/gone", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        mock_subprocess.return_value = MagicMock(stdout="")
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_repo / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")
        with pytest.raises(click.ClickException, match="not found locally"):
            _validate_resume_preconditions(tmp_repo, log)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_fails_on_missing_prd(self, mock_subprocess, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/missing.md", task_rel="cOS_tasks/tasks.md",
        )
        mock_subprocess.return_value = MagicMock(stdout="  feat/x\n")
        with pytest.raises(click.ClickException, match="PRD file not found"):
            _validate_resume_preconditions(tmp_repo, log)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_fails_on_missing_task_file(self, mock_subprocess, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/missing.md",
        )
        mock_subprocess.return_value = MagicMock(stdout="  feat/x\n")
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        with pytest.raises(click.ClickException, match="Task file not found"):
            _validate_resume_preconditions(tmp_repo, log)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_succeeds_when_all_conditions_met(self, mock_subprocess, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        mock_subprocess.return_value = MagicMock(stdout="  feat/x\n")
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_repo / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")
        _validate_resume_preconditions(tmp_repo, log)  # Should not raise


class TestComputeNextPhase:
    def test_plan_to_implement(self):
        assert _compute_next_phase("plan") == "implement"

    def test_implement_to_review(self):
        assert _compute_next_phase("implement") == "review"

    def test_review_to_review(self):
        assert _compute_next_phase("review") == "review"

    def test_fix_to_review(self):
        assert _compute_next_phase("fix") == "review"

    def test_decision_to_deliver(self):
        assert _compute_next_phase("decision") == "deliver"

    def test_unknown_returns_none(self):
        assert _compute_next_phase("unknown") is None


class TestResumeFromRun:
    """Task 4: Phase resumption and log continuity."""

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_resume_after_plan_runs_implement_review_deliver(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """When last_successful_phase is 'plan', skip plan and run implement+review+deliver."""
        save_config(tmp_repo, config)
        existing_log = RunLog(
            run_id="r-resume", prompt="Add feature", status=RunStatus.FAILED,
            branch_name="colonyos/add_feature", prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[_fake_phase_result(Phase.PLAN)],
        )

        mock_run.side_effect = [
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/add_feature",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="plan",
        )

        log = run(
            "Add feature", repo_root=tmp_repo, config=config,
            resume_from=resume_state,
        )

        assert log.status == RunStatus.COMPLETED
        # Plan was from the original run, then implement+review+decision+learn+deliver added
        phase_types = [p.phase for p in log.phases]
        assert phase_types[0] == Phase.PLAN  # Original
        assert Phase.IMPLEMENT in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_resume_after_implement_skips_plan_and_implement(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """When last_successful_phase is 'implement', skip plan+implement, run review+deliver."""
        save_config(tmp_repo, config)
        existing_log = RunLog(
            run_id="r-resume2", prompt="Add feature", status=RunStatus.FAILED,
            branch_name="colonyos/add_feature", prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[
                _fake_phase_result(Phase.PLAN),
                _fake_phase_result(Phase.IMPLEMENT),
            ],
        )

        mock_run.side_effect = [
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/add_feature",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="implement",
        )

        log = run(
            "Add feature", repo_root=tmp_repo, config=config,
            resume_from=resume_state,
        )

        assert log.status == RunStatus.COMPLETED
        # Plan mock should NOT have been called for plan or implement
        # mock_run calls: decision + learn + deliver = 3
        assert mock_run.call_count == 3

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_resume_after_review_failure_reruns_review_loop(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """When review/fix failed, re-enter the review loop from the top."""
        save_config(tmp_repo, config)
        existing_log = RunLog(
            run_id="r-resume3", prompt="Add feature", status=RunStatus.FAILED,
            branch_name="colonyos/add_feature", prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[
                _fake_phase_result(Phase.PLAN),
                _fake_phase_result(Phase.IMPLEMENT),
                _fake_phase_result(Phase.REVIEW, success=False),
            ],
        )

        mock_run.side_effect = [
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/add_feature",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="implement",
        )

        log = run(
            "Add feature", repo_root=tmp_repo, config=config,
            resume_from=resume_state,
        )

        assert log.status == RunStatus.COMPLETED
        assert mock_parallel.call_count == 1  # Review was re-entered

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_log_continuity_preserves_original_phases(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """Resumed log has both original and new phases, written to same file."""
        save_config(tmp_repo, config)
        original_plan = _fake_phase_result(Phase.PLAN)
        existing_log = RunLog(
            run_id="r-continuity", prompt="Add feature", status=RunStatus.FAILED,
            branch_name="colonyos/add_feature", prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[original_plan],
        )
        _save_run_log(tmp_repo, existing_log)

        mock_run.side_effect = [
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/add_feature",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="plan",
        )

        log = run(
            "Add feature", repo_root=tmp_repo, config=config,
            resume_from=resume_state,
        )

        assert log.phases[0] is original_plan  # Original phase preserved
        assert len(log.phases) > 1  # New phases appended

        # Verify the JSON file has all phases
        log_path = tmp_repo / ".colonyos" / "runs" / "r-continuity.json"
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data["phases"]) == len(log.phases)
        assert data["status"] == "completed"

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_resume_after_decision_runs_only_deliver(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """When last_successful_phase is 'decision', only deliver runs."""
        save_config(tmp_repo, config)
        existing_log = RunLog(
            run_id="r-decision", prompt="Add feature", status=RunStatus.FAILED,
            branch_name="colonyos/add_feature", prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[
                _fake_phase_result(Phase.PLAN),
                _fake_phase_result(Phase.IMPLEMENT),
                _approve_review_result(),
                PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                            duration_ms=50, session_id="s",
                            artifacts={"result": "VERDICT: GO"}),
            ],
        )

        mock_run.side_effect = [
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]

        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/add_feature",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="decision",
        )

        log = run(
            "Add feature", repo_root=tmp_repo, config=config,
            resume_from=resume_state,
        )

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 2  # Learn + deliver
        assert mock_parallel.call_count == 0  # No reviews

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_run_sets_resume_fields_in_log(
        self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig
    ):
        """Normal (non-resume) runs persist branch_name, prd_rel, task_rel."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.branch_name is not None
        assert log.prd_rel is not None
        assert log.task_rel is not None

        # Verify persisted in JSON
        runs_dir = tmp_repo / ".colonyos" / "runs"
        log_files = list(runs_dir.glob("*.json"))
        assert len(log_files) == 1
        data = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert data["branch_name"] == log.branch_name
        assert data["prd_rel"] == log.prd_rel
        assert data["task_rel"] == log.task_rel


class TestRunIdValidation:
    """Path traversal protection for run_id in _load_run_log."""

    def test_rejects_path_traversal_dotdot(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="must not contain"):
            _load_run_log(tmp_repo, "../../etc/passwd")

    def test_rejects_forward_slash(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="must not contain"):
            _load_run_log(tmp_repo, "foo/bar")

    def test_rejects_backslash(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="must not contain"):
            _load_run_log(tmp_repo, "foo\\bar")

    def test_rejects_empty_run_id(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="must not be empty"):
            _load_run_log(tmp_repo, "")

    def test_accepts_valid_run_id(self, tmp_repo: Path):
        """Valid run IDs with hyphens, underscores, dots should work."""
        # This should raise "not found" rather than "invalid"
        with pytest.raises(click.ClickException, match="Run log not found"):
            _load_run_log(tmp_repo, "run-20260101-abc123")


class TestRelPathValidation:
    """Path containment validation for prd_rel and task_rel."""

    def test_rejects_prd_rel_escaping_repo(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "escape.json").write_text(json.dumps({
            "run_id": "escape", "prompt": "test", "status": "failed",
            "phases": [], "total_cost_usd": 0.0,
            "prd_rel": "../../etc/passwd",
            "task_rel": "cOS_tasks/tasks.md",
        }), encoding="utf-8")
        with pytest.raises(click.ClickException, match="escapes repository root"):
            _load_run_log(tmp_repo, "escape")

    def test_rejects_task_rel_escaping_repo(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "escape2.json").write_text(json.dumps({
            "run_id": "escape2", "prompt": "test", "status": "failed",
            "phases": [], "total_cost_usd": 0.0,
            "prd_rel": "cOS_prds/prd.md",
            "task_rel": "../../../etc/shadow",
        }), encoding="utf-8")
        with pytest.raises(click.ClickException, match="escapes repository root"):
            _load_run_log(tmp_repo, "escape2")


class TestSchemaValidation:
    """Schema validation for corrupted run log JSON."""

    def test_missing_required_field_raises(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        # Missing 'prompt' field
        (runs_dir / "bad-schema.json").write_text(json.dumps({
            "run_id": "bad-schema", "status": "failed",
            "phases": [],
        }), encoding="utf-8")
        with pytest.raises(click.ClickException, match="Invalid run log schema"):
            _load_run_log(tmp_repo, "bad-schema")

    def test_invalid_phase_value_raises(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "bad-phase.json").write_text(json.dumps({
            "run_id": "bad-phase", "prompt": "test", "status": "failed",
            "phases": [{"phase": "nonexistent", "success": True}],
        }), encoding="utf-8")
        with pytest.raises(click.ClickException, match="Invalid run log schema"):
            _load_run_log(tmp_repo, "bad-phase")

    def test_invalid_status_value_raises(self, tmp_repo: Path):
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "bad-status.json").write_text(json.dumps({
            "run_id": "bad-status", "prompt": "test", "status": "invalid_status",
            "phases": [],
        }), encoding="utf-8")
        with pytest.raises(click.ClickException, match="Invalid run log schema"):
            _load_run_log(tmp_repo, "bad-status")


class TestGitBranchArgTermination:
    """Verify -- argument termination in git branch --list call."""

    @patch("colonyos.orchestrator.subprocess.run")
    def test_git_branch_uses_double_dash(self, mock_subprocess, tmp_repo: Path):
        log = RunLog(
            run_id="r1", prompt="test", status=RunStatus.FAILED,
            branch_name="--delete", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        mock_subprocess.return_value = MagicMock(stdout="  --delete\n")
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_repo / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")
        _validate_resume_preconditions(tmp_repo, log)
        # Verify the subprocess call includes -- before branch name
        call_args = mock_subprocess.call_args[0][0]
        assert call_args == ["git", "branch", "--list", "--", "--delete"]


class TestResumeAuditTrail:
    """Resume events are recorded in the run log JSON."""

    def test_resume_events_recorded(self, tmp_repo: Path):
        log = RunLog(
            run_id="r-audit", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        # First save (no resume)
        _save_run_log(tmp_repo, log)
        data = json.loads((tmp_repo / ".colonyos" / "runs" / "r-audit.json").read_text())
        assert data.get("resume_events", []) == []

        # Save with resumed=True
        _save_run_log(tmp_repo, log, resumed=True)
        data = json.loads((tmp_repo / ".colonyos" / "runs" / "r-audit.json").read_text())
        assert len(data["resume_events"]) == 1
        assert isinstance(data["resume_events"][0], str)  # ISO timestamp

    def test_multiple_resume_events_accumulate(self, tmp_repo: Path):
        log = RunLog(
            run_id="r-multi", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
        )
        _save_run_log(tmp_repo, log)
        _save_run_log(tmp_repo, log, resumed=True)
        _save_run_log(tmp_repo, log, resumed=True)
        data = json.loads((tmp_repo / ".colonyos" / "runs" / "r-multi.json").read_text())
        assert len(data["resume_events"]) == 2


class TestPrepareResume:
    """Tests for the public prepare_resume() function."""

    def test_returns_resume_state(self, tmp_repo: Path):
        log = RunLog(
            run_id="r-prep", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
            phases=[_fake_phase_result(Phase.PLAN)],
        )
        _save_run_log(tmp_repo, log)
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_repo / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")

        with patch("colonyos.orchestrator.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout="  feat/x\n")
            state = prepare_resume(tmp_repo, "r-prep")

        assert isinstance(state, ResumeState)
        assert state.branch_name == "feat/x"
        assert state.prd_rel == "cOS_prds/prd.md"
        assert state.task_rel == "cOS_tasks/tasks.md"
        assert state.last_successful_phase == "plan"

    def test_raises_on_no_successful_phases(self, tmp_repo: Path):
        log = RunLog(
            run_id="r-nosuccess", prompt="test", status=RunStatus.FAILED,
            branch_name="feat/x", prd_rel="cOS_prds/prd.md", task_rel="cOS_tasks/tasks.md",
            phases=[_fake_phase_result(Phase.PLAN, success=False)],
        )
        _save_run_log(tmp_repo, log)
        (tmp_repo / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_repo / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")

        with patch("colonyos.orchestrator.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout="  feat/x\n")
            with pytest.raises(click.ClickException, match="No successful phases"):
                prepare_resume(tmp_repo, "r-nosuccess")

    def test_rejects_path_traversal(self, tmp_repo: Path):
        with pytest.raises(click.ClickException, match="must not contain"):
            prepare_resume(tmp_repo, "../../etc/passwd")


class TestHeartbeat:
    """Task 6.1: Tests for heartbeat file."""

    def test_heartbeat_created_at_phase_start(self, tmp_repo: Path):
        from colonyos.orchestrator import _touch_heartbeat as touch_heartbeat
        heartbeat_path = tmp_repo / ".colonyos" / "runs" / "heartbeat"
        assert not heartbeat_path.exists()
        touch_heartbeat(tmp_repo)
        assert heartbeat_path.exists()

    def test_heartbeat_path_is_correct(self, tmp_repo: Path):
        from colonyos.orchestrator import _touch_heartbeat as touch_heartbeat
        touch_heartbeat(tmp_repo)
        heartbeat_path = tmp_repo / ".colonyos" / "runs" / "heartbeat"
        assert heartbeat_path.exists()

    def test_heartbeat_touch_updates_mtime(self, tmp_repo: Path):
        import time
        from colonyos.orchestrator import _touch_heartbeat as touch_heartbeat
        touch_heartbeat(tmp_repo)
        heartbeat_path = tmp_repo / ".colonyos" / "runs" / "heartbeat"
        mtime1 = heartbeat_path.stat().st_mtime
        time.sleep(0.05)
        touch_heartbeat(tmp_repo)
        mtime2 = heartbeat_path.stat().st_mtime
        assert mtime2 >= mtime1


class TestLearningsInjection:
    """Tests for learnings injection into implement and fix prompts."""

    def test_implement_prompt_includes_learnings(self, tmp_repo: Path, config: ColonyConfig):
        lpath = learnings_path(tmp_repo)
        lpath.parent.mkdir(parents=True, exist_ok=True)
        entries = [LearningEntry("code-quality", "Always add docstrings")]
        append_learnings(tmp_repo, "run-001", "2026-03-17", "test", entries)

        system, _ = _build_implement_prompt(config, "prd.md", "tasks.md", "branch", repo_root=tmp_repo)
        assert "## Learnings from Past Runs" in system
        assert "Always add docstrings" in system

    def test_implement_prompt_no_crash_when_no_ledger(self, tmp_repo: Path, config: ColonyConfig):
        system, _ = _build_implement_prompt(config, "prd.md", "tasks.md", "branch", repo_root=tmp_repo)
        assert "Learnings" not in system

    def test_implement_prompt_no_learnings_without_repo_root(self, config: ColonyConfig):
        system, _ = _build_implement_prompt(config, "prd.md", "tasks.md", "branch")
        assert "Learnings" not in system

    def test_fix_prompt_includes_learnings(self, tmp_repo: Path, config: ColonyConfig):
        lpath = learnings_path(tmp_repo)
        lpath.parent.mkdir(parents=True, exist_ok=True)
        entries = [LearningEntry("testing", "Write tests first")]
        append_learnings(tmp_repo, "run-001", "2026-03-17", "test", entries)

        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", "fix this", 1, repo_root=tmp_repo
        )
        assert "## Learnings from Past Runs" in system
        assert "Write tests first" in system

    def test_fix_prompt_no_crash_when_no_ledger(self, tmp_repo: Path, config: ColonyConfig):
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", "fix this", 1, repo_root=tmp_repo
        )
        assert "Learnings" not in system


class TestParseLearnOutput:
    def test_parses_valid_entries(self):
        text = (
            "- **[code-quality]** Always add docstrings\n"
            "- **[testing]** Run pytest before committing\n"
        )
        entries = _parse_learn_output(text)
        assert len(entries) == 2
        assert entries[0].category == "code-quality"
        assert entries[1].category == "testing"

    def test_ignores_invalid_categories(self):
        text = "- **[invalid-cat]** Something\n"
        entries = _parse_learn_output(text)
        assert len(entries) == 0

    def test_truncates_long_entries(self):
        long_text = "x" * 200
        text = f"- **[code-quality]** {long_text}\n"
        entries = _parse_learn_output(text)
        assert len(entries[0].text) <= 150


class TestBuildLearnPrompt:
    def test_returns_system_and_user(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_learn_prompt(config, tmp_repo)
        assert "review artifacts" in system.lower() or "review" in system.lower()
        assert config.reviews_dir in user


@patch("colonyos.orchestrator.run_phases_parallel_sync")
@patch("colonyos.orchestrator.run_phase_sync")
class TestLearnPhaseWiring:
    """Tests for learn phase wiring in the orchestrator pipeline."""

    def test_learn_phase_produces_phase_result(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase runs and produces a PhaseResult with Phase.LEARN."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        phase_types = [p.phase for p in log.phases]
        assert Phase.LEARN in phase_types

    def test_learn_phase_runs_on_nogo(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase runs even on NO-GO verdict."""
        config.max_fix_iterations = 0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            _fake_phase_result(Phase.LEARN),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.LEARN in phase_types

    def test_learn_phase_skipped_when_disabled(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase is skipped when config.learnings.enabled is False."""
        config.learnings = LearningsConfig(enabled=False)
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        phase_types = [p.phase for p in log.phases]
        assert Phase.LEARN not in phase_types
        assert log.status == RunStatus.COMPLETED

    def test_learn_phase_failure_does_not_block_deliver(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase failure does not prevent deliver from running."""
        save_config(tmp_repo, config)

        def learn_side_effect(*args, **kwargs):
            # Determine which call this is by checking side_effect_calls
            return learn_side_effect.results.pop(0)

        learn_side_effect.results = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            PhaseResult(phase=Phase.LEARN, success=False, error="Budget exceeded"),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_run.side_effect = learn_side_effect
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.LEARN in phase_types
        assert Phase.DELIVER in phase_types

    def test_learn_phase_exception_does_not_block_deliver(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Exception in learn phase does not prevent deliver from running."""
        save_config(tmp_repo, config)

        call_count = [0]
        results = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            RuntimeError("Agent crashed"),  # learn phase raises
            _fake_phase_result(Phase.DELIVER),
        ]

        def side_effect(*args, **kwargs):
            r = results[call_count[0]]
            call_count[0] += 1
            if isinstance(r, Exception):
                raise r
            return r

        mock_run.side_effect = side_effect
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.LEARN in phase_types
        assert Phase.DELIVER in phase_types
        learn_result = [p for p in log.phases if p.phase == Phase.LEARN][0]
        assert learn_result.success is False

    def test_learn_phase_budget(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase budget is min(0.50, config.budget.per_phase / 2)."""
        config.budget.per_phase = 1.0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add feature", repo_root=tmp_repo, config=config)

        # Find the learn phase call
        for call in mock_run.call_args_list:
            if call[0][0] == Phase.LEARN:
                assert call.kwargs["budget_usd"] == 0.50
                assert call.kwargs["allowed_tools"] == ["Read", "Glob", "Grep"]
                break

    def test_learn_phase_uses_read_only_tools(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """Learn phase uses read-only tools."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add feature", repo_root=tmp_repo, config=config)

        for call in mock_run.call_args_list:
            if call[0][0] == Phase.LEARN:
                tools = call.kwargs["allowed_tools"]
                assert tools == ["Read", "Glob", "Grep"]
                assert "Write" not in tools
                assert "Bash" not in tools
                break


# ---------------------------------------------------------------------------
# GitHub issue integration tests
# ---------------------------------------------------------------------------


class TestBuildPlanPromptWithIssue:
    def test_without_issue(self, config: ColonyConfig) -> None:
        system, user = _build_plan_prompt("test prompt", config, "prd.md", "tasks.md")
        assert "GitHub issue" not in system

    def test_with_issue(self, config: ColonyConfig) -> None:
        system, user = _build_plan_prompt(
            "test prompt", config, "prd.md", "tasks.md",
            source_issue=42,
            source_issue_url="https://github.com/org/repo/issues/42",
        )
        assert "#42" in system
        assert "https://github.com/org/repo/issues/42" in system
        assert "Source Issue" in system

    def test_user_prompt_unchanged(self, config: ColonyConfig) -> None:
        _, user = _build_plan_prompt(
            "my feature", config, "prd.md", "tasks.md",
            source_issue=1,
        )
        assert "my feature" in user


class TestBuildDeliverPromptWithIssue:
    def test_without_issue(self, config: ColonyConfig) -> None:
        system, _ = _build_deliver_prompt(config, "prd.md", "branch")
        assert "Closes" not in system

    def test_with_issue(self, config: ColonyConfig) -> None:
        system, _ = _build_deliver_prompt(config, "prd.md", "branch", source_issue=42)
        assert "Closes #42" in system
        assert "#42" in system


class TestSaveRunLogSourceIssue:
    def test_persists_source_issue_fields(self, tmp_repo: Path) -> None:
        log = RunLog(
            run_id="r-issue", prompt="test", status=RunStatus.COMPLETED,
            source_issue=42,
            source_issue_url="https://github.com/org/repo/issues/42",
        )
        path = _save_run_log(tmp_repo, log)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["source_issue"] == 42
        assert data["source_issue_url"] == "https://github.com/org/repo/issues/42"

    def test_persists_none_when_no_issue(self, tmp_repo: Path) -> None:
        log = RunLog(run_id="r-no-issue", prompt="test", status=RunStatus.COMPLETED)
        path = _save_run_log(tmp_repo, log)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["source_issue"] is None
        assert data["source_issue_url"] is None


class TestLoadRunLogSourceIssue:
    def test_loads_source_issue(self, tmp_repo: Path) -> None:
        log = RunLog(
            run_id="r-load", prompt="test", status=RunStatus.FAILED,
            source_issue=7,
            source_issue_url="https://github.com/org/repo/issues/7",
        )
        _save_run_log(tmp_repo, log)
        loaded = _load_run_log(tmp_repo, "r-load")
        assert loaded.source_issue == 7
        assert loaded.source_issue_url == "https://github.com/org/repo/issues/7"

    def test_backward_compat_missing_fields(self, tmp_repo: Path) -> None:
        runs_dir = tmp_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "old.json").write_text(json.dumps({
            "run_id": "old", "prompt": "test", "status": "failed",
            "phases": [], "total_cost_usd": 0.0,
        }), encoding="utf-8")
        loaded = _load_run_log(tmp_repo, "old")
        assert loaded.source_issue is None
        assert loaded.source_issue_url is None


class TestBuildCeoPromptWithIssues:
    @patch("colonyos.github.fetch_open_issues")
    def test_injects_open_issues(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        from colonyos.github import GitHubIssue
        mock_fetch.return_value = [
            GitHubIssue(number=1, title="Bug fix", body="", labels=["bug"]),
            GitHubIssue(number=2, title="New feature", body="", labels=[]),
        ]
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        assert "## Open Issues" in user
        assert "#1: Bug fix" in user
        assert "#2: New feature" in user
        assert "Issue: #N" in user

    @patch("colonyos.github.fetch_open_issues")
    def test_no_issues_no_section(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        mock_fetch.return_value = []
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        assert "## Open Issues" not in user

    @patch("colonyos.github.fetch_open_issues", side_effect=Exception("fail"))
    def test_exception_non_blocking(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        # Should not raise — just proceed without issues
        assert "Analyze this project" in user


class TestPerPhaseModelRouting:
    """Verify that orchestrator passes config.get_model(Phase.XXX) to run_phase_sync for each phase."""

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_each_phase_receives_correct_model(self, mock_run, mock_parallel, tmp_repo: Path):
        """With per-phase overrides, each run_phase_sync call gets the right model string."""
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[REVIEWER_PERSONA],
            model="sonnet",
            phase_models={"plan": "haiku", "implement": "opus", "deliver": "haiku"},
            budget=BudgetConfig(per_phase=1.0, per_run=10.0),
            phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True),
        )
        save_config(tmp_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Test model routing", repo_root=tmp_repo, config=config)

        # Collect model= kwarg from each run_phase_sync call
        calls = mock_run.call_args_list
        model_by_phase = {}
        for call in calls:
            phase_arg = call.args[0] if call.args else call.kwargs.get("phase")
            model_kwarg = call.kwargs.get("model")
            model_by_phase[phase_arg] = model_kwarg

        # Overridden phases get their override
        assert model_by_phase[Phase.PLAN] == "haiku"
        assert model_by_phase[Phase.IMPLEMENT] == "opus"
        assert model_by_phase[Phase.DELIVER] == "haiku"
        # Non-overridden phases fall back to global model
        assert model_by_phase[Phase.DECISION] == "sonnet"
        assert model_by_phase[Phase.LEARN] == "sonnet"

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_parallel_receives_correct_model(self, mock_run, mock_parallel, tmp_repo: Path):
        """Review phase (via parallel runner) also receives the per-phase model."""
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[REVIEWER_PERSONA],
            model="sonnet",
            phase_models={"review": "opus"},
            budget=BudgetConfig(per_phase=1.0, per_run=10.0),
            phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True),
        )
        save_config(tmp_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Test review model", repo_root=tmp_repo, config=config)

        # The parallel call for review passes a list of dicts, each with model=
        parallel_call = mock_parallel.call_args
        call_dicts = parallel_call.args[0]
        for call_dict in call_dicts:
            assert call_dict["model"] == "opus"


class TestSaveReviewArtifact:
    """Tests for _save_review_artifact subdirectory support."""

    def test_saves_to_root_when_no_subdirectory(self, tmp_path: Path):
        path = _save_review_artifact(
            tmp_path, "cOS_reviews", "test.md", "content"
        )
        assert path == tmp_path / "cOS_reviews" / "test.md"
        assert path.read_text(encoding="utf-8") == "content"

    def test_saves_to_subdirectory(self, tmp_path: Path):
        path = _save_review_artifact(
            tmp_path, "cOS_reviews", "decision.md", "verdict",
            subdirectory="decisions",
        )
        assert path == tmp_path / "cOS_reviews" / "decisions" / "decision.md"
        assert path.read_text(encoding="utf-8") == "verdict"

    def test_creates_nested_subdirectories(self, tmp_path: Path):
        path = _save_review_artifact(
            tmp_path, "cOS_reviews", "round1.md", "review",
            subdirectory="reviews/staff_engineer",
        )
        expected = tmp_path / "cOS_reviews" / "reviews" / "staff_engineer" / "round1.md"
        assert path == expected
        assert path.exists()

    def test_rejects_path_traversal(self, tmp_path: Path):
        with pytest.raises(ValueError, match="escapes"):
            _save_review_artifact(
                tmp_path, "cOS_reviews", "bad.md", "evil",
                subdirectory="../../etc",
            )

    def test_rejects_path_traversal_in_filename(self, tmp_path: Path):
        with pytest.raises(ValueError, match="escapes"):
            _save_review_artifact(
                tmp_path, "cOS_reviews", "../../etc/passwd", "evil",
            )


class TestExtractPrNumberFromLog:
    """Tests for _extract_pr_number_from_log helper."""

    def test_extracts_from_deliver_artifacts(self) -> None:
        log = RunLog(run_id="test", prompt="test", status=RunStatus.RUNNING)
        log.phases.append(PhaseResult(
            phase=Phase.DELIVER,
            success=True,
            artifacts={"pr_url": "https://github.com/org/repo/pull/42"},
        ))
        assert _extract_pr_number_from_log(log) == 42

    def test_returns_none_when_no_deliver_phase(self) -> None:
        log = RunLog(run_id="test", prompt="test", status=RunStatus.RUNNING)
        log.phases.append(PhaseResult(phase=Phase.IMPLEMENT, success=True))
        assert _extract_pr_number_from_log(log) is None

    def test_returns_none_when_no_pr_url(self) -> None:
        log = RunLog(run_id="test", prompt="test", status=RunStatus.RUNNING)
        log.phases.append(PhaseResult(
            phase=Phase.DELIVER, success=True, artifacts={},
        ))
        assert _extract_pr_number_from_log(log) is None


class TestBuildCiFixPrompt:
    """Tests for _build_ci_fix_prompt."""

    def test_returns_system_and_user(self, tmp_path: Path) -> None:
        config = ColonyConfig()
        system, user = _build_ci_fix_prompt(
            config, "my-branch", "CI failure context here", 1, 3,
        )
        assert "my-branch" in system
        assert "CI failure context here" in system
        assert "attempt 1 of 3" in user

    def test_includes_branch_name(self, tmp_path: Path) -> None:
        config = ColonyConfig()
        system, user = _build_ci_fix_prompt(
            config, "feature/fix-tests", "", 2, 5,
        )
        assert "feature/fix-tests" in user


class TestRunCiFixLoop:
    """Integration tests for _run_ci_fix_loop."""

    def _make_log_with_deliver(self, pr_url: str = "https://github.com/o/r/pull/42") -> RunLog:
        log = RunLog(run_id="test", prompt="test", status=RunStatus.RUNNING)
        log.phases.append(PhaseResult(
            phase=Phase.DELIVER,
            success=True,
            artifacts={"pr_url": pr_url},
        ))
        return log

    def test_skips_when_no_pr_number(self, tmp_path: Path) -> None:
        config = ColonyConfig()
        log = RunLog(run_id="test", prompt="test", status=RunStatus.RUNNING)
        # No deliver phase → should return immediately
        _run_ci_fix_loop(config, tmp_path, log, "main")
        # No CI_FIX phases should be added
        assert not any(p.phase == Phase.CI_FIX for p in log.phases)

    def test_skips_when_all_checks_pass(self, tmp_path: Path) -> None:
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        log = self._make_log_with_deliver()
        checks = [CheckResult(name="test", state="completed", conclusion="success")]
        with patch("colonyos.ci.poll_pr_checks", return_value=checks):
            _run_ci_fix_loop(config, tmp_path, log, "main")
        assert not any(p.phase == Phase.CI_FIX for p in log.phases)

    def test_runs_fix_cycle_on_failure(self, tmp_path: Path) -> None:
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        log = self._make_log_with_deliver()
        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        pass_checks = [CheckResult(name="test", state="completed", conclusion="success")]
        mock_phase = PhaseResult(phase=Phase.CI_FIX, success=True, cost_usd=0.01)

        with patch("colonyos.ci.poll_pr_checks", side_effect=[failed_checks, pass_checks]), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}), \
             patch("colonyos.orchestrator.run_phase_sync", return_value=mock_phase), \
             patch("colonyos.orchestrator.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0)  # git push
            _run_ci_fix_loop(config, tmp_path, log, "main")

        ci_fix_phases = [p for p in log.phases if p.phase == Phase.CI_FIX]
        assert len(ci_fix_phases) == 1
        assert ci_fix_phases[0].success

    def test_push_failure_breaks_loop(self, tmp_path: Path) -> None:
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        config.ci_fix.max_retries = 3
        log = self._make_log_with_deliver()
        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        mock_phase = PhaseResult(phase=Phase.CI_FIX, success=True, cost_usd=0.01)

        with patch("colonyos.ci.poll_pr_checks", return_value=failed_checks), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}), \
             patch("colonyos.orchestrator.run_phase_sync", return_value=mock_phase), \
             patch("colonyos.orchestrator.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=1, stderr="push rejected")  # git push fails
            _run_ci_fix_loop(config, tmp_path, log, "main")

        # Only one attempt should have been made despite max_retries=3
        ci_fix_phases = [p for p in log.phases if p.phase == Phase.CI_FIX]
        assert len(ci_fix_phases) == 1

    def test_agent_failure_continues_retries(self, tmp_path: Path) -> None:
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        config.ci_fix.max_retries = 2
        log = self._make_log_with_deliver()
        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        fail_phase = PhaseResult(phase=Phase.CI_FIX, success=False, error="agent crash")

        with patch("colonyos.ci.poll_pr_checks", return_value=failed_checks), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}), \
             patch("colonyos.orchestrator.run_phase_sync", return_value=fail_phase):
            _run_ci_fix_loop(config, tmp_path, log, "main")

        # Both attempts should have been recorded
        ci_fix_phases = [p for p in log.phases if p.phase == Phase.CI_FIX]
        assert len(ci_fix_phases) == 2
        assert all(not p.success for p in ci_fix_phases)

    def test_budget_guard_stops_loop(self, tmp_path: Path) -> None:
        """CI fix loop must stop when per-run budget is exhausted (FR21)."""
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        config.ci_fix.max_retries = 3
        # per_run=0.20, per_phase=0.10, prior cost=0.15 → remaining=0.05
        # which is < per_phase → first attempt should already be blocked.
        config.budget.per_run = 0.20
        config.budget.per_phase = 0.10

        log = self._make_log_with_deliver()
        log.phases.append(PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.15))

        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]

        with patch("colonyos.ci.poll_pr_checks", return_value=failed_checks), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}):
            _run_ci_fix_loop(config, tmp_path, log, "main")

        # No CI fix attempts should have been made — budget exhausted
        ci_fix_phases = [p for p in log.phases if p.phase == Phase.CI_FIX]
        assert len(ci_fix_phases) == 0

    def test_budget_guard_allows_then_stops(self, tmp_path: Path) -> None:
        """Budget guard allows first attempt but blocks second when exhausted."""
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        config.ci_fix.max_retries = 3
        # per_run=1.00, per_phase=0.50, prior cost=0.20 → remaining=0.80
        # Attempt 1 ok. After attempt 1 cost = 0.20+0.50=0.70, remaining=0.30
        # which is < per_phase(0.50) → attempt 2 blocked.
        config.budget.per_run = 1.00
        config.budget.per_phase = 0.50

        log = self._make_log_with_deliver()
        log.phases.append(PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.20))

        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        mock_phase = PhaseResult(phase=Phase.CI_FIX, success=True, cost_usd=0.50)

        with patch("colonyos.ci.poll_pr_checks", return_value=failed_checks), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}), \
             patch("colonyos.orchestrator.run_phase_sync", return_value=mock_phase), \
             patch("colonyos.orchestrator.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0)
            _run_ci_fix_loop(config, tmp_path, log, "main")

        # Only 1 attempt ran; second blocked by budget
        ci_fix_phases = [p for p in log.phases if p.phase == Phase.CI_FIX]
        assert len(ci_fix_phases) == 1

    def test_budget_guard_caps_phase_budget(self, tmp_path: Path) -> None:
        """run_phase_sync budget should be min(per_phase, remaining)."""
        from colonyos.ci import CheckResult
        config = ColonyConfig()
        config.ci_fix.max_retries = 1
        config.budget.per_run = 1.00
        config.budget.per_phase = 0.50

        log = self._make_log_with_deliver()
        # Already spent 0.60 → remaining is 0.40 which is ≥ per_phase? No,
        # 0.40 < 0.50 so the guard would block.  Use 0.30 instead →
        # remaining = 0.70 > per_phase so attempt runs, but budget_usd
        # should be min(0.50, 0.70) = 0.50.  That doesn't test the cap.
        # Use per_run=0.80, per_phase=0.50, spent=0.40 → remaining=0.40
        # which is < per_phase → blocked.  We need remaining ≥ per_phase
        # but < per_phase too, which is impossible.  The cap only matters
        # when remaining ≥ per_phase (otherwise we break out).
        # So test: per_run=1.00, per_phase=0.80, spent=0.60 →
        # remaining=0.40 < 0.80 → blocked.
        # Ok — we can only observe the cap when remaining ≥ per_phase AND
        # remaining < per_phase.  That's contradictory for a single call.
        # The cap is: min(per_phase, remaining). When remaining ≥ per_phase,
        # cap = per_phase.  When remaining < per_phase, we break.
        # So the min() only produces a different value if remaining < per_phase,
        # but in that case the guard blocks.  The min() is thus a
        # belt-and-suspenders safety; we can still verify it's passed.
        # Use: per_run=1.00, per_phase=0.50, spent=0.20 → remaining=0.80
        # budget_usd = min(0.50, 0.80) = 0.50.
        log.phases.append(PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.20))

        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        pass_checks = [CheckResult(name="test", state="completed", conclusion="success")]
        mock_phase = PhaseResult(phase=Phase.CI_FIX, success=True, cost_usd=0.10)

        with patch("colonyos.ci.poll_pr_checks", side_effect=[failed_checks, pass_checks]), \
             patch("colonyos.ci.fetch_check_logs", return_value={"step": "error"}), \
             patch("colonyos.orchestrator.run_phase_sync", return_value=mock_phase) as mock_rps, \
             patch("colonyos.orchestrator.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0)
            _run_ci_fix_loop(config, tmp_path, log, "main")

        # budget_usd = min(per_phase=0.50, remaining=0.80) = 0.50
        call_kwargs = mock_rps.call_args[1]
        assert call_kwargs["budget_usd"] == pytest.approx(0.50, abs=0.01)


# ---------------------------------------------------------------------------
# Base branch targeting tests
# ---------------------------------------------------------------------------


class TestBaseBranchDeliverPrompt:
    """Tests for base_branch parameter in _build_deliver_prompt."""

    def test_no_base_branch(self) -> None:
        from colonyos.orchestrator import _build_deliver_prompt
        config = ColonyConfig()
        system, user = _build_deliver_prompt(
            config, "cOS_prds/test.md", "colonyos/test",
        )
        assert "--base" not in system
        assert "Target branch" not in user

    def test_with_base_branch(self) -> None:
        from colonyos.orchestrator import _build_deliver_prompt
        config = ColonyConfig()
        system, user = _build_deliver_prompt(
            config, "cOS_prds/test.md", "colonyos/test",
            base_branch="colonyos/auth-middleware",
        )
        assert "colonyos/auth-middleware" in system
        assert "--base" in system
        assert "colonyos/auth-middleware" in user

    def test_base_branch_with_source_issue(self) -> None:
        from colonyos.orchestrator import _build_deliver_prompt
        config = ColonyConfig()
        system, user = _build_deliver_prompt(
            config, "cOS_prds/test.md", "colonyos/test",
            source_issue=42,
            base_branch="colonyos/feat",
        )
        assert "Closes #42" in system
        assert "colonyos/feat" in system


class TestBaseBranchValidation:
    """Tests for base_branch validation in orchestrator.run()."""

    def test_invalid_base_branch_raises(self, tmp_path: Path) -> None:
        from colonyos.orchestrator import run as run_orchestrator
        from colonyos.models import PreflightError

        config = ColonyConfig(
            project=ProjectInfo(name="test", description="test", stack="python"),
        )

        # Initialize a git repo for pre-flight to work
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

        with pytest.raises(PreflightError, match="does not exist"):
            run_orchestrator(
                "test prompt",
                repo_root=tmp_path,
                config=config,
                base_branch="nonexistent/branch",
                offline=True,
            )

    def test_base_branch_with_invalid_chars_rejected(self, tmp_path: Path) -> None:
        """Defense-in-depth: base_branch with shell metacharacters is rejected at orchestrator level."""
        from colonyos.orchestrator import run as run_orchestrator
        from colonyos.models import PreflightError

        config = ColonyConfig(
            project=ProjectInfo(name="test", description="test", stack="python"),
        )

        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

        with pytest.raises(PreflightError, match="invalid characters"):
            run_orchestrator(
                "test prompt",
                repo_root=tmp_path,
                config=config,
                base_branch="main; rm -rf /",
                offline=True,
            )

    def test_base_branch_with_dotdot_rejected(self, tmp_path: Path) -> None:
        """Paths with .. traversal are rejected."""
        from colonyos.orchestrator import run as run_orchestrator
        from colonyos.models import PreflightError

        config = ColonyConfig(
            project=ProjectInfo(name="test", description="test", stack="python"),
        )

        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

        with pytest.raises(PreflightError, match="invalid characters"):
            run_orchestrator(
                "test prompt",
                repo_root=tmp_path,
                config=config,
                base_branch="../etc/passwd",
                offline=True,
            )


class TestNamedStashOnBranchRollback:
    """The finally block in run() should use a named stash with 'colonyos-{branch}' message."""

    def test_stash_command_includes_branch_name(self) -> None:
        """Verify the stash push command uses -m with branch-identifying message."""
        import ast
        import inspect
        from colonyos.orchestrator import run as run_fn

        source = inspect.getsource(run_fn)
        assert "git\", \"stash\", \"push\", \"--include-untracked\", \"-m\"" in source
        assert "colonyos-{branch_name}" in source
