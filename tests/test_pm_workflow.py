from pathlib import Path

from colonyos_pm.models import HumanInterventionRecord, RiskTier
from colonyos_pm.personas import select_persona
from colonyos_pm.questions import generate_clarifying_questions
from colonyos_pm.risk import assess_risk
from colonyos_pm.storage import LocalArtifactStore
from colonyos_pm.workflow import run_pm_workflow


def test_generate_clarifying_questions_is_bounded_and_nonempty() -> None:
    questions = generate_clarifying_questions("Build autonomous PM workflow")
    assert 4 <= len(questions) <= 12
    assert all(question.text.strip() for question in questions)


def test_persona_selection_uses_category_mapping() -> None:
    questions = generate_clarifying_questions("Build autonomous PM workflow")
    risk_question = [q for q in questions if q.category == "risk"][0]
    persona = select_persona(risk_question)
    assert "YC partner" in persona.value


def test_risk_assessment_escalates_for_sensitive_keywords() -> None:
    assessment = assess_risk("Implement billing auth migration with production secrets")
    assert assessment.tier in {RiskTier.HIGH, RiskTier.CRITICAL}
    assert assessment.escalate_to_human is True


def test_workflow_outputs_prd_and_handoff_payload() -> None:
    artifacts = run_pm_workflow("Create an autonomous PM workflow for product specs")
    assert artifacts.work_id.startswith("pmw-")
    assert "## Goals" in artifacts.prd_markdown
    assert "## Functional Requirements" in artifacts.prd_markdown
    assert "tests-first step before code changes" in artifacts.prd_markdown
    assert artifacts.handoff_payload.target_flow == "generate_tasks"
    assert artifacts.handoff_payload.metadata["prd_format"] == "markdown"
    assert artifacts.handoff_payload.metadata["execution_policy"] == "tests_first"


def test_local_artifact_store_writes_expected_files(tmp_path: Path) -> None:
    store = LocalArtifactStore(base_dir=str(tmp_path / "generated"))
    artifacts = run_pm_workflow("Build PM workflow")
    result = store.save_workflow_artifacts(artifacts)

    assert Path(result["work_dir"]).exists()
    assert Path(result["prd_path"]).exists()
    assert Path(result["bundle_path"]).exists()

    memory_path = store.save_human_intervention(
        HumanInterventionRecord(
            work_id=artifacts.work_id,
            tier=artifacts.risk_assessment.tier,
            decision="approved-with-constraints",
            guidance="Require human review for payment-related specs.",
        )
    )
    assert Path(memory_path).exists()
