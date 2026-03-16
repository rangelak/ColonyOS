import threading
import time
from pathlib import Path
from unittest.mock import patch

import colonyos_pm.workflow as workflow_module
from colonyos_pm.models import HumanInterventionRecord, RiskTier
from colonyos_pm.models import AutonomousAnswer, ClarifyingQuestion, ExpertPersona, RiskAssessment
from colonyos_pm.personas import select_persona
from colonyos_pm.prd import build_prd_markdown
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

    def test_parallel_answer_generation_preserves_question_order(
        self, monkeypatch
    ) -> None:
        questions = [
            ClarifyingQuestion(id="q1", text="First question", category="goal"),
            ClarifyingQuestion(id="q2", text="Second question", category="users"),
            ClarifyingQuestion(id="q3", text="Third question", category="technical"),
        ]
        thread_ids: set[int] = set()

        monkeypatch.setattr(
            workflow_module,
            "generate_clarifying_questions",
            lambda prompt: questions,
        )
        monkeypatch.setattr(
            workflow_module,
            "assess_risk",
            lambda prompt: RiskAssessment(
                tier=RiskTier.LOW,
                score=1,
                escalate_to_human=False,
                rationale=["safe"],
            ),
        )
        monkeypatch.setattr(
            workflow_module,
            "build_prd_markdown",
            lambda prompt, answers: "## Goals\n\n- Ship it",
        )
        monkeypatch.setattr(
            workflow_module,
            "select_persona",
            lambda question: ExpertPersona.SENIOR_ENGINEER,
        )

        def fake_generate_answer(
            question: ClarifyingQuestion, persona: ExpertPersona
        ) -> AutonomousAnswer:
            thread_ids.add(threading.get_ident())
            time.sleep(0.2)
            return AutonomousAnswer(
                question_id=question.id,
                question=question.text,
                answer=f"answer for {question.id}",
                answered_by=persona,
                reasoning=f"reasoning for {question.id}",
            )

        monkeypatch.setattr(
            workflow_module,
            "generate_autonomous_answer",
            fake_generate_answer,
        )

        started_at = time.perf_counter()
        artifacts = run_pm_workflow("Parallelize answers")
        elapsed = time.perf_counter() - started_at

        assert [a.question_id for a in artifacts.autonomous_answers] == ["q1", "q2", "q3"]
        assert len(thread_ids) > 1
        assert elapsed < 0.45


class TestPrdFormatting:
    def test_build_prd_normalizes_to_task_prd_style(self) -> None:
        answers = [
            AutonomousAnswer(
                question_id="q1",
                question="What matters most?",
                answer="Execution-ready scope.",
                answered_by=ExpertPersona.STARTUP_CEO,
                reasoning="It unlocks delivery.",
            )
        ]
        raw_prd = """# PRD: Example

## Clarifying Questions And Autonomous Answers

### 1. What matters most?
- Answer: Execution-ready scope.
- Answered by: CEO of an insanely fast-growing startup
- Reasoning: It unlocks delivery.

## Introduction/Overview

Hello
"""

        with patch("colonyos_pm.prd.chat", return_value=raw_prd):
            prd_markdown = build_prd_markdown("Prompt", answers)

        assert "**Answer:** Execution-ready scope." in prd_markdown
        assert "**Answered by:** CEO of an insanely fast-growing startup" in prd_markdown
        assert "**Reasoning:** It unlocks delivery." in prd_markdown
        assert "\n---\n\n## Introduction/Overview" in prd_markdown


class TestLocalArtifactStore:
    def test_writes_prd_and_bundle(self, tmp_path: Path) -> None:
        store = LocalArtifactStore(
            base_dir=str(tmp_path / "generated"),
            tasks_dir=str(tmp_path / "tasks"),
        )
        artifacts = run_pm_workflow("Build PM workflow")
        result = store.save_workflow_artifacts(artifacts)

        assert Path(result["work_dir"]).exists()
        assert Path(result["prd_path"]).exists()
        prd_content = Path(result["prd_path"]).read_text()
        assert len(prd_content) > 100
        assert Path(result["bundle_path"]).exists()
        assert Path(result["task_prd_path"]).exists()
        task_prd_content = Path(result["task_prd_path"]).read_text()
        assert task_prd_content.startswith("# PRD:")

    def test_saves_human_intervention_record(self, tmp_path: Path) -> None:
        store = LocalArtifactStore(
            base_dir=str(tmp_path / "generated"),
            tasks_dir=str(tmp_path / "tasks"),
        )
        memory_path = store.save_human_intervention(
            HumanInterventionRecord(
                work_id="pmw-test123",
                tier=RiskTier.HIGH,
                decision="approved-with-constraints",
                guidance="Require human review for payment-related specs.",
            )
        )
        assert Path(memory_path).exists()
