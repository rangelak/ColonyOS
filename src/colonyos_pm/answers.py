from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import AutonomousAnswer, ClarifyingQuestion, ExpertPersona
from colonyos_pm.prompts import ANSWER_GENERATION_SYSTEM, PERSONA_IDENTITIES


def generate_autonomous_answer(
    question: ClarifyingQuestion, persona: ExpertPersona
) -> AutonomousAnswer:
    system = ANSWER_GENERATION_SYSTEM.format(
        persona_identity=PERSONA_IDENTITIES[persona]
    )
    user = f"Question: {question.text}"

    data = chat_json(system=system, user=user, temperature=0.6)
    answer_text = data.get("answer", "") if isinstance(data, dict) else ""
    reasoning = data.get("reasoning", "") if isinstance(data, dict) else ""

    return AutonomousAnswer(
        question_id=question.id,
        question=question.text,
        answer=answer_text,
        answered_by=persona,
        reasoning=reasoning,
    )
