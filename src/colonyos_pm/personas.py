from __future__ import annotations

from colonyos_pm.models import ClarifyingQuestion, ExpertPersona


CATEGORY_TO_PERSONA: dict[str, ExpertPersona] = {
    "goal": ExpertPersona.STARTUP_CEO,
    "users": ExpertPersona.YC_PARTNER,
    "artifact": ExpertPersona.STARTUP_CEO,
    "autonomy": ExpertPersona.YC_PARTNER,
    "quality": ExpertPersona.STARTUP_CEO,
    "handoff": ExpertPersona.SENIOR_ENGINEER,
    "validation": ExpertPersona.SENIOR_ENGINEER,
    "risk": ExpertPersona.YC_PARTNER,
    "scope": ExpertPersona.STARTUP_CEO,
    "design": ExpertPersona.SENIOR_DESIGNER,
}


def select_persona(question: ClarifyingQuestion) -> ExpertPersona:
    return CATEGORY_TO_PERSONA.get(question.category, ExpertPersona.SENIOR_ENGINEER)
