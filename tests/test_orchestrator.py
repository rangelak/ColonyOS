from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, PhasesConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunStatus
from colonyos.orchestrator import run, _format_personas_block, _build_run_id


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "prds").mkdir()
    (tmp_path / "tasks").mkdir()
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
        phases=PhasesConfig(plan=True, implement=True, deliver=True),
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


class TestFormatPersonasBlock:
    def test_with_personas(self):
        personas = [
            Persona(role="Engineer", expertise="APIs", perspective="Scale")
        ]
        block = _format_personas_block(personas)
        assert "Engineer" in block
        assert "APIs" in block

    def test_without_personas(self):
        block = _format_personas_block([])
        assert "senior engineer" in block


class TestBuildRunId:
    def test_format(self):
        rid = _build_run_id("test prompt")
        assert rid.startswith("run-")
        assert len(rid) > 20


class TestRun:
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_run_success(self, mock_run, tmp_repo: Path, config: ColonyConfig):
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
        prd = tmp_repo / "prds" / "20260316_120000_prd_test.md"
        prd.write_text("# PRD", encoding="utf-8")

        mock_run.side_effect = [
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run(
            "Implement test",
            repo_root=tmp_repo,
            config=config,
            from_prd=str(prd),
        )

        assert log.status == RunStatus.COMPLETED
        assert len(log.phases) == 2
        assert mock_run.call_count == 2

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_run_log_saved(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_config(tmp_repo, config)
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            _fake_phase_result(Phase.DELIVER),
        ]

        log = run("Add feature", repo_root=tmp_repo, config=config)

        runs_dir = tmp_repo / ".colonyos" / "runs"
        assert runs_dir.exists()
        log_files = list(runs_dir.glob("*.json"))
        assert len(log_files) == 1
