from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, PhasesConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunStatus
from colonyos.orchestrator import (
    run,
    _format_personas_block,
    _build_persona_agents,
    _build_fix_prompt,
    _build_run_id,
    _parse_parent_tasks,
    _persona_slug,
    _reviewer_personas,
    _build_persona_review_prompt,
    _extract_review_verdict,
    _collect_review_findings,
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
        assert phases == [Phase.CEO, Phase.PLAN, Phase.IMPLEMENT, Phase.REVIEW, Phase.DECISION, Phase.FIX, Phase.DELIVER]

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
        reviewers = _reviewer_personas(config)
        assert len(reviewers) == 1
        assert reviewers[0].role == "Engineer"

    def test_no_reviewers(self):
        config = ColonyConfig(
            personas=[NON_REVIEWER_PERSONA],
        )
        assert _reviewer_personas(config) == []

    def test_all_reviewers(self):
        p1 = Persona(role="A", expertise="a", perspective="a", reviewer=True)
        p2 = Persona(role="B", expertise="b", perspective="b", reviewer=True)
        config = ColonyConfig(personas=[p1, p2])
        assert len(_reviewer_personas(config)) == 2


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
        assert _extract_review_verdict("VERDICT: approve\nLooks good.") == "approve"

    def test_request_changes(self):
        assert _extract_review_verdict("VERDICT: request-changes\nNeeds fixes.") == "request-changes"

    def test_case_insensitive(self):
        assert _extract_review_verdict("Verdict: Approve") == "approve"

    def test_defaults_to_request_changes(self):
        assert _extract_review_verdict("No clear verdict.") == "request-changes"


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
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 4
        assert mock_parallel.call_count == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_phase_skipped_when_disabled(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        config.phases.review = False
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert len(log.phases) == 3
        assert mock_run.call_count == 3
        phase_types = [p.phase for p in log.phases]
        assert Phase.REVIEW not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_skipped_when_no_reviewer_personas(self, mock_run, tmp_repo: Path):
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
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 3

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_saves_artifacts(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add tests", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        assert reviews_dir.exists()
        review_files = list(reviews_dir.glob("*.md"))
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
    def test_multiple_reviewer_personas(self, mock_run, mock_parallel, tmp_repo: Path):
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
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [_approve_review_result()]

        run("Add feature", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        filenames = {f.name for f in reviews_dir.glob("*.md")}
        assert any("review_round1_engineer" in f for f in filenames)
