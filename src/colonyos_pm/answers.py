from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import AutonomousAnswer, ClarifyingQuestion, ExpertPersona

PERSONA_SYSTEM_PROMPTS: dict[ExpertPersona, str] = {
    ExpertPersona.SENIOR_DESIGNER: (
        "You are a super senior product designer who previously led design at "
        "Apple and Airbnb. You think in terms of user experience, clarity, "
        "simplicity, and design systems. You are opinionated and concrete."
    ),
    ExpertPersona.SENIOR_ENGINEER: (
        "You are a super senior software engineer with Google-level systems "
        "judgment. You think in terms of architecture, scalability, "
        "deterministic contracts, and operational reliability. You are direct "
        "and specific."
    ),
    ExpertPersona.STARTUP_CEO: (
        "You are the CEO of an insanely fast-growing startup. You think in "
        "terms of velocity, leverage, scope control, and shipping the highest "
        "impact work first. You are decisive and opinionated."
    ),
    ExpertPersona.YC_PARTNER: (
        "You are a YC partner. You think in terms of market fit, founder "
        "judgment, compounding systems, and building things that compound "
        "value over time. You challenge weak assumptions."
    ),
}


def generate_autonomous_answer(
    question: ClarifyingQuestion, persona: ExpertPersona
) -> AutonomousAnswer:
    system = (
        f"{PERSONA_SYSTEM_PROMPTS[persona]}\n\n"
        "You are answering a clarifying question as part of an autonomous PM "
        "workflow. Your answer should be concrete, opinionated, and directly "
        "useful for writing a PRD.\n\n"
        "Return JSON with this exact schema:\n"
        '{"answer": "<your concrete answer>", "reasoning": "<why this is the right call>"}'
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
