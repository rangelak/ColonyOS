from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, PhasesConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunStatus
from colonyos.orchestrator import (
    DEFAULT_CEO_PERSONA,
    _build_ceo_prompt,
    _extract_feature_prompt,
    run_ceo,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "cOS_prds").mkdir()
    (tmp_path / "cOS_tasks").mkdir()
    (tmp_path / "cOS_reviews").mkdir()
    (tmp_path / "cOS_proposals").mkdir()
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def config() -> ColonyConfig:
    return ColonyConfig(
        project=ProjectInfo(name="TestApp", description="A test app", stack="Python"),
        personas=[
            Persona(role="Engineer", expertise="Backend", perspective="Scale", reviewer=True)
        ],
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=10.0),
        phases=PhasesConfig(),
    )


def _fake_ceo_result(success: bool = True) -> PhaseResult:
    return PhaseResult(
        phase=Phase.CEO,
        success=success,
        cost_usd=0.01,
        duration_ms=100,
        session_id="test-session",
        artifacts={
            "result": (
                "## Proposal: Add Webhooks\n\n"
                "### Rationale\n"
                "Webhooks enable real-time integrations.\n\n"
                "### Feature Request\n"
                "Add a webhook system that lets users subscribe to events."
            )
        },
    )


class TestDefaultCeoPersona:
    def test_has_required_fields(self):
        assert DEFAULT_CEO_PERSONA.role == "Product CEO"
        assert "strategy" in DEFAULT_CEO_PERSONA.expertise.lower()
        assert "impactful" in DEFAULT_CEO_PERSONA.perspective.lower()


class TestBuildCeoPrompt:
    def test_contains_project_info(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test_proposal.md", tmp_repo)
        assert "TestApp" in system
        assert "A test app" in system
        assert "Python" in system

    def test_contains_default_persona(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test_proposal.md", tmp_repo)
        assert "Product CEO" in system

    def test_uses_custom_ceo_persona(self, tmp_repo: Path):
        custom_persona = Persona(
            role="Growth CEO",
            expertise="Growth hacking",
            perspective="What moves the needle on metrics?",
        )
        config = ColonyConfig(
            project=ProjectInfo(name="App", description="d", stack="s"),
            ceo_persona=custom_persona,
        )
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Growth CEO" in system
        assert "Growth hacking" in system

    def test_contains_vision_when_set(self, tmp_repo: Path):
        config = ColonyConfig(
            project=ProjectInfo(name="App", description="d", stack="s"),
            vision="Become the #1 developer tool",
        )
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Become the #1 developer tool" in system

    def test_contains_no_vision_placeholder_when_empty(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "No vision statement configured" in system

    def test_user_prompt_mentions_output(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "20260317_120000_proposal_ceo.md", tmp_repo)
        assert "proposal" in user.lower() or "format" in user.lower()

    def test_contains_directory_references(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "cOS_prds" in system
        assert "cOS_tasks" in system

    def test_injects_changelog_into_user_prompt(self, tmp_repo: Path, config: ColonyConfig):
        changelog_path = tmp_repo / "CHANGELOG.md"
        changelog_path.write_text("# Changelog\n\n## 20260317 — Widget System\nAdded widgets.\n")
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Widget System" in user
        assert "MUST NOT duplicate" in user

    def test_no_changelog_still_works(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Development History" in user
        assert "propose" in user.lower()


class TestExtractFeaturePrompt:
    def test_extracts_feature_request_section(self):
        text = (
            "## Proposal: Add Webhooks\n\n"
            "### Rationale\nWebhooks are useful.\n\n"
            "### Feature Request\n"
            "Add a webhook system that lets users subscribe to events."
        )
        result = _extract_feature_prompt(text)
        assert result == "Add a webhook system that lets users subscribe to events."

    def test_fallback_to_full_text(self):
        text = "Just build a cool feature."
        result = _extract_feature_prompt(text)
        assert result == "Just build a cool feature."

    def test_empty_text(self):
        result = _extract_feature_prompt("")
        assert result == "No proposal generated."

    def test_feature_request_with_following_section(self):
        text = (
            "### Feature Request\n"
            "Build X.\n\n"
            "## Notes\nSome notes."
        )
        result = _extract_feature_prompt(text)
        assert result == "Build X."


class TestRunCeo:
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_returns_prompt_and_result(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        mock_run.return_value = _fake_ceo_result()

        prompt, result = run_ceo(tmp_repo, config)

        assert "webhook" in prompt.lower()
        assert result.success is True
        assert result.phase == Phase.CEO

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_read_only_tools(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["allowed_tools"] == ["Read", "Glob", "Grep"]

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_saves_proposal_artifact(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        proposals_dir = tmp_repo / "cOS_proposals"
        proposal_files = list(proposals_dir.glob("*.md"))
        assert len(proposal_files) == 1
        content = proposal_files[0].read_text(encoding="utf-8")
        assert "Webhooks" in content

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_ceo_phase(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        call_args = mock_run.call_args
        assert call_args[0][0] == Phase.CEO

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_custom_ceo_persona(self, mock_run, tmp_repo: Path):
        custom = Persona(role="Growth CEO", expertise="Growth", perspective="Metrics")
        config = ColonyConfig(
            project=ProjectInfo(name="App", description="d", stack="s"),
            ceo_persona=custom,
        )
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        system_prompt = mock_run.call_args.kwargs["system_prompt"]
        assert "Growth CEO" in system_prompt

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_default_persona_when_none(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        assert config.ceo_persona is None
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        system_prompt = mock_run.call_args.kwargs["system_prompt"]
        assert "Product CEO" in system_prompt

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_failed_ceo_result(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=False,
            error="Budget exceeded",
            artifacts={"result": ""},
        )

        prompt, result = run_ceo(tmp_repo, config)

        assert result.success is False
        assert prompt == ""


class TestCeoIntegration:
    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_flow_ceo_to_pipeline(self, mock_run, mock_parallel, tmp_repo: Path, config: ColonyConfig):
        """CEO output feeds into the pipeline as a prompt string."""
        from colonyos.orchestrator import run as run_orchestrator

        ceo_result = _fake_ceo_result()
        plan_result = PhaseResult(phase=Phase.PLAN, success=True, cost_usd=0.01, duration_ms=100, session_id="s", artifacts={"result": "done"})
        impl_result = PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.01, duration_ms=100, session_id="s", artifacts={"result": "done"})
        approve_result = PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01, duration_ms=100, session_id="s", artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        decision_result = PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": "VERDICT: GO"})
        deliver_result = PhaseResult(phase=Phase.DELIVER, success=True, cost_usd=0.01, duration_ms=100, session_id="s", artifacts={"result": "done"})

        learn_result = PhaseResult(phase=Phase.LEARN, success=True, cost_usd=0.01, duration_ms=50, session_id="s", artifacts={"result": ""})

        mock_run.side_effect = [
            ceo_result,  # CEO phase (run_ceo)
            plan_result,
            impl_result,
            decision_result,
            learn_result,
            deliver_result,
        ]
        mock_parallel.return_value = [approve_result]

        save_config(tmp_repo, config)

        prompt, ceo_phase = run_ceo(tmp_repo, config)
        assert "webhook" in prompt.lower()

        log = run_orchestrator(prompt, repo_root=tmp_repo, config=config)
        assert log.status == RunStatus.COMPLETED

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_ceo_reads_only(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        """Verify CEO phase uses read-only tools only."""
        mock_run.return_value = _fake_ceo_result()

        run_ceo(tmp_repo, config)

        call_kwargs = mock_run.call_args.kwargs
        tools = call_kwargs["allowed_tools"]
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Write" not in tools
        assert "Edit" not in tools
        assert "Bash" not in tools


class TestCeoOpenIssuesContext:
    """Task 6.1: CEO prompt with open issues context."""

    @patch("colonyos.github.fetch_open_issues")
    def test_open_issues_injected(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        from colonyos.github import GitHubIssue
        mock_fetch.return_value = [
            GitHubIssue(number=10, title="Support dark mode", body="", labels=["enhancement"]),
            GitHubIssue(number=11, title="Fix login bug", body="", labels=["bug"]),
        ]
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        assert "## Open Issues" in user
        assert "#10: Support dark mode" in user
        assert "#11: Fix login bug" in user
        assert "Issue: #N" in user

    @patch("colonyos.github.fetch_open_issues")
    def test_empty_issues_no_section(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        mock_fetch.return_value = []
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        assert "## Open Issues" not in user

    @patch("colonyos.github.fetch_open_issues", side_effect=RuntimeError("network"))
    def test_failure_non_blocking(self, mock_fetch, tmp_repo: Path, config: ColonyConfig) -> None:
        _, user = _build_ceo_prompt(config, "proposal.md", tmp_repo)
        assert "Analyze this project" in user
        assert "## Open Issues" not in user
