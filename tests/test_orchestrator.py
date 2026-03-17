from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, PhasesConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunStatus
from colonyos.orchestrator import (
    run,
    _format_personas_block,
    _format_review_personas_block,
    _build_persona_agents,
    _build_review_persona_agents,
    _build_review_prompt,
    _build_fix_prompt,
    _build_run_id,
    _parse_parent_tasks,
    _persona_slug,
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
        personas=[
            Persona(role="Engineer", expertise="Backend", perspective="Scale")
        ],
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=3.0),
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


class TestFormatReviewPersonasBlock:
    def test_with_personas(self):
        personas = [
            Persona(role="Engineer", expertise="APIs", perspective="Scale")
        ]
        block = _format_review_personas_block(personas)
        assert "engineer" in block
        assert "review" in block.lower()

    def test_without_personas(self):
        block = _format_review_personas_block([])
        assert "senior engineer" in block


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


class TestBuildReviewPersonaAgents:
    def test_builds_review_agents_per_persona(self):
        personas = [
            Persona(role="Steve Jobs", expertise="Product vision", perspective="Simplify"),
            Persona(role="Linus Torvalds", expertise="Kernel", perspective="Correctness"),
        ]
        agents = _build_review_persona_agents(personas)
        assert "steve_jobs" in agents
        assert "linus_torvalds" in agents
        assert "reviewer" in agents["steve_jobs"].description
        assert "reviewing" in agents["steve_jobs"].prompt.lower()

    def test_review_agents_have_read_only_tools(self):
        personas = [
            Persona(role="Engineer", expertise="Backend", perspective="Scale"),
        ]
        agents = _build_review_persona_agents(personas)
        tools = agents["engineer"].tools
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Write" not in tools
        assert "Edit" not in tools
        assert "Bash" not in tools

    def test_empty_personas(self):
        agents = _build_review_persona_agents([])
        assert agents == {}


class TestBuildReviewPrompt:
    def test_output_contains_key_elements(self):
        config = ColonyConfig(
            personas=[
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ],
        )
        system, user = _build_review_prompt(
            config, "cOS_prds/test.md", "feat/test", "1.0 Add auth"
        )
        assert "review" in system.lower()
        assert "cOS_prds/test.md" in system
        assert "feat/test" in system
        assert "1.0 Add auth" in system
        assert "1.0 Add auth" in user

    def test_includes_persona_block(self):
        config = ColonyConfig(
            personas=[
                Persona(role="Steve Jobs", expertise="Product", perspective="Simplify")
            ],
        )
        system, _ = _build_review_prompt(
            config, "prd.md", "branch", "task desc"
        )
        assert "steve_jobs" in system


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
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_run_success_with_review(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),  # per-task review
            _fake_phase_result(Phase.REVIEW),  # final holistic review
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 6

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
        # No REVIEW phase in the log
        phase_types = [p.phase for p in log.phases]
        assert Phase.REVIEW not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_failure_stops_run(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW, success=False),  # per-task review fails
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        assert any(p.phase == Phase.REVIEW for p in log.phases)

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_with_task_file(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Review phase parses parent tasks from the task file."""
        save_config(tmp_repo, config)

        from colonyos.naming import planning_names
        names = planning_names("Add auth feature")
        task_file = tmp_repo / config.tasks_dir / names.task_filename
        task_file.write_text(
            "## Tasks\n\n"
            "- [ ] 1.0 Add auth model\n"
            "  - [ ] 1.1 Write tests\n"
            "- [ ] 2.0 Add auth routes\n"
            "  - [ ] 2.1 Write tests\n",
            encoding="utf-8",
        )

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),  # task 1 review
            _fake_phase_result(Phase.REVIEW),  # task 2 review
            _fake_phase_result(Phase.REVIEW),  # final holistic review
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add auth feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        assert mock_run.call_count == 7

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_saves_artifacts(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Review phase saves markdown artifacts to reviews_dir."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),  # per-task
            _fake_phase_result(Phase.REVIEW),  # final holistic
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add tests", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        assert reviews_dir.exists()
        review_files = list(reviews_dir.glob("*.md"))
        assert len(review_files) == 3  # 1 per-task + 1 final + 1 decision

        filenames = {f.name for f in review_files}
        assert any("review_task_1" in f for f in filenames)
        assert any("review_final" in f for f in filenames)
        assert any("decision" in f for f in filenames)

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_review_persona_agents_passed(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Review phase passes persona agents to run_phase_sync."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),  # per-task
            _fake_phase_result(Phase.REVIEW),  # final holistic
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        run("Add tests", repo_root=tmp_repo, config=config)

        review_call = mock_run.call_args_list[2]
        assert review_call.kwargs.get("agents") is not None
        assert "engineer" in review_call.kwargs["agents"]

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

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_from_prd_skips_plan(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        prd = tmp_repo / "cOS_prds" / "20260316_120000_prd_test.md"
        prd.write_text("# PRD", encoding="utf-8")

        mock_run.side_effect = [
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),  # per-task
            _fake_phase_result(Phase.REVIEW),  # final holistic
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run(
            "Implement test",
            repo_root=tmp_repo,
            config=config,
            from_prd=str(prd),
        )

        assert log.status == RunStatus.COMPLETED

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_run_log_saved(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        runs_dir = tmp_repo / ".colonyos" / "runs"
        assert runs_dir.exists()
        log_files = list(runs_dir.glob("*.json"))
        assert len(log_files) == 1

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_decision_nogo_stops_pipeline(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Decision gate NO-GO verdict prevents delivery when max_fix_iterations=0."""
        config.max_fix_iterations = 0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: NO-GO\n\nToo many issues."}),
        ]

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
            "VERDICT: NO-GO\n\nUnresolved Issues:\n- Bug in auth", 1,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_contains_base_and_fix(self):
        config = ColonyConfig(max_fix_iterations=2)
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "feat/branch",
            "VERDICT: NO-GO", 1,
        )
        # Base instructions
        assert "ColonyOS" in system
        # Fix template content
        assert "Fix Phase" in system
        assert "fix iteration 1 of 2" in system.lower()

    def test_system_embeds_decision_text(self):
        config = ColonyConfig(max_fix_iterations=3)
        decision = "VERDICT: NO-GO\n\nUnresolved Issues:\n- Missing tests"
        system, _ = _build_fix_prompt(
            config, "prd.md", "tasks.md", "branch", decision, 2,
        )
        assert "Missing tests" in system
        assert "NO-GO" in system

    def test_user_prompt_contains_context(self):
        config = ColonyConfig(max_fix_iterations=2)
        _, user = _build_fix_prompt(
            config, "cOS_prds/prd.md", "cOS_tasks/tasks.md",
            "feat/fix", "verdict text", 1,
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


class TestFixLoop:
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_nogo_fix_go_delivers(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """NO-GO -> fix -> review -> GO -> deliver (success path)."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),   # per-task
            _fake_phase_result(Phase.REVIEW),   # holistic
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nIssues found."}),
            # Fix iteration 1
            _fake_phase_result(Phase.FIX),      # fix
            _fake_phase_result(Phase.REVIEW),   # holistic re-review
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            # Deliver
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_max_iterations_exhausted(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """NO-GO -> fix -> NO-GO -> fix -> NO-GO -> fail."""
        config.max_fix_iterations = 2
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nBad code."}),
            # Fix iteration 1
            _fake_phase_result(Phase.FIX),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nStill bad."}),
            # Fix iteration 2
            _fake_phase_result(Phase.FIX),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nStill bad."}),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types
        assert phase_types.count(Phase.FIX) == 2

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_zero_max_iterations_failfast(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """max_fix_iterations=0 preserves fail-fast behavior."""
        config.max_fix_iterations = 0
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX not in phase_types
        assert Phase.DELIVER not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_fix_iterations_in_runlog(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Fix iterations appear as Phase.FIX in the run log."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            _fake_phase_result(Phase.FIX),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        fix_phases = [p for p in log.phases if p.phase == Phase.FIX]
        assert len(fix_phases) == 1
        assert fix_phases[0].success is True

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_unknown_verdict_no_fix_loop(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """UNKNOWN verdict does NOT trigger fix loop (proceeds to deliver)."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "No clear verdict here."}),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX not in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_fix_phase_failure_fails_run(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Phase failure during fix iteration fails the run."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            _fake_phase_result(Phase.FIX, success=False),  # fix fails
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_budget_exhaustion_stops_fix_loop(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Fix loop stops when remaining per-run budget is insufficient."""
        config.budget = BudgetConfig(per_phase=1.0, per_run=3.0)
        save_config(tmp_repo, config)
        # Each phase costs 1.0, so after plan(1)+impl(1)+review(1) = 3.0,
        # we've used up the budget. But we have per-task + holistic + decision
        # so let's use cost_usd values to exhaust budget.
        mock_run.side_effect = [
            PhaseResult(phase=Phase.PLAN, success=True, cost_usd=0.8,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.8,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.5,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.5,
                        duration_ms=50, session_id="s", artifacts={"result": "done"}),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.5,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO"}),
            # Budget: 3.0 - (0.8+0.8+0.5+0.5+0.5) = -0.1 -> insufficient
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.FIX not in phase_types

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_fix_saves_iteration_tagged_artifacts(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Fix iteration review artifacts have iteration-tagged filenames."""
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.REVIEW),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: NO-GO\n\nIssues."}),
            _fake_phase_result(Phase.FIX),
            _fake_phase_result(Phase.REVIEW),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        run("Add feature", repo_root=tmp_repo, config=config)

        reviews_dir = tmp_repo / config.reviews_dir
        filenames = {f.name for f in reviews_dir.glob("*.md")}
        assert "review_final_fix1.md" in filenames
        assert "decision_fix1.md" in filenames
