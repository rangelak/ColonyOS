from pathlib import Path

from colonyos_pm.models import HumanInterventionRecord, RiskTier
from colonyos_pm.personas import select_persona
from colonyos_pm.questions import generate_clarifying_questions
from colonyos_pm.risk import assess_risk
from colonyos_pm.storage import LocalArtifactStore
from colonyos_pm.workflow import run_pm_workflow


class TestQuestionGeneration:
    def test_returns_bounded_list(self) -> None:
        questions = generate_clarifying_questions("Build autonomous PM workflow")
        assert 4 <= len(questions) <= 12

    def test_all_questions_have_text_and_category(self) -> None:
        questions = generate_clarifying_questions("Build autonomous PM workflow")
        for q in questions:
            assert q.text.strip()
            assert q.category.strip()

    def test_vague_prompt_still_generates_questions(self) -> None:
        questions = generate_clarifying_questions("make it better")
        assert len(questions) >= 4


class TestPersonaRouting:
    def test_risk_question_routes_to_yc_partner(self) -> None:
        questions = generate_clarifying_questions("Build autonomous PM workflow")
        risk_questions = [q for q in questions if q.category == "risk"]
        assert risk_questions
        persona = select_persona(risk_questions[0])
        assert "YC partner" in persona.value

    def test_design_question_routes_to_designer(self) -> None:
        questions = generate_clarifying_questions("Build autonomous PM workflow")
        design_questions = [q for q in questions if q.category == "design"]
        assert design_questions
        persona = select_persona(design_questions[0])
        assert "designer" in persona.value.lower()


class TestRiskAssessment:
    def test_low_risk_for_benign_prompt(self) -> None:
        assessment = assess_risk("Add a settings page for user preferences")
        assert assessment.tier == RiskTier.LOW
        assert assessment.escalate_to_human is False

    def test_high_risk_for_sensitive_prompt(self) -> None:
        assessment = assess_risk("Implement billing auth migration with production secrets")
        assert assessment.tier in {RiskTier.HIGH, RiskTier.CRITICAL}
        assert assessment.escalate_to_human is True

    def test_rationale_is_populated(self) -> None:
        assessment = assess_risk("Build a simple dashboard")
        assert len(assessment.rationale) > 0


class TestFullWorkflow:
    def test_produces_all_artifacts(self) -> None:
        artifacts = run_pm_workflow("Create an autonomous PM workflow for product specs")
        assert artifacts.work_id.startswith("pmw-")
        assert len(artifacts.clarifying_questions) >= 4
        assert len(artifacts.autonomous_answers) >= 4
        assert artifacts.prd_markdown.strip()
        assert artifacts.handoff_payload.target_flow == "generate_tasks"
        assert artifacts.handoff_payload.metadata["execution_policy"] == "tests_first"

    def test_prd_contains_required_sections(self) -> None:
        artifacts = run_pm_workflow("Create an autonomous PM workflow for product specs")
        for section in ["## Goals", "## Functional Requirements", "## Non-Goals"]:
            assert section in artifacts.prd_markdown

    def test_prd_includes_tests_first_requirement(self) -> None:
        artifacts = run_pm_workflow("Create an autonomous PM workflow for product specs")
        assert "tests-first" in artifacts.prd_markdown.lower()

    def test_answers_have_persona_and_reasoning(self) -> None:
        artifacts = run_pm_workflow("Build PM workflow")
        for answer in artifacts.autonomous_answers:
            assert answer.answered_by.value
            assert answer.reasoning.strip()
            assert answer.answer.strip()


class TestLocalArtifactStore:
    def test_writes_prd_and_bundle(self, tmp_path: Path) -> None:
        store = LocalArtifactStore(base_dir=str(tmp_path / "generated"))
        artifacts = run_pm_workflow("Build PM workflow")
        result = store.save_workflow_artifacts(artifacts)

        assert Path(result["work_dir"]).exists()
        assert Path(result["prd_path"]).exists()
        prd_content = Path(result["prd_path"]).read_text()
        assert len(prd_content) > 100
        assert Path(result["bundle_path"]).exists()

    def test_saves_human_intervention_record(self, tmp_path: Path) -> None:
        store = LocalArtifactStore(base_dir=str(tmp_path / "generated"))
        memory_path = store.save_human_intervention(
            HumanInterventionRecord(
                work_id="pmw-test123",
                tier=RiskTier.HIGH,
                decision="approved-with-constraints",
                guidance="Require human review for payment-related specs.",
            )
        )
        assert Path(memory_path).exists()
