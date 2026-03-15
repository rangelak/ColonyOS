from __future__ import annotations

from colonyos_pm.models import AutonomousAnswer, ClarifyingQuestion, ExpertPersona


def _default_answer_for_category(category: str) -> tuple[str, str]:
    mapping: dict[str, tuple[str, str]] = {
        "goal": (
            "Improve spec quality, reduce ambiguity, and increase downstream coding success.",
            "Optimizing the full planning-to-execution path creates higher compounding leverage than optimizing one local metric.",
        ),
        "users": (
            "Mixed audience: founder/operator, coding agents, and future internal operators.",
            "A planning system serving only one persona collapses orchestration value and degrades handoff quality.",
        ),
        "artifact": (
            "A traditional PRD that follows the existing create_prd contract.",
            "Deterministic artifact structure makes downstream task generation and automation reliable.",
        ),
        "autonomy": (
            "The workflow should autonomously answer clarifying questions and escalate only for high-risk exceptions.",
            "Autonomy is required for velocity, while exception-based escalation preserves control.",
        ),
        "quality": (
            "Use an elite quality bar: explicit scope, clear requirements, strong rationale, and readable output.",
            "High planning quality improves first-pass implementation and reduces rework.",
        ),
        "handoff": (
            "Emit a deterministic handoff package for the task-generation phase.",
            "A strict handoff contract prevents interpretation drift between PM and implementation agents.",
        ),
        "validation": (
            "For v1, validate artifact completeness and output files only.",
            "Lightweight validation keeps scope focused while preserving traceability.",
        ),
        "risk": (
            "Classify work into low/medium/high/critical tiers and escalate only high/critical by default.",
            "Tiered autonomy protects sensitive workflows without slowing normal execution.",
        ),
        "scope": (
            "Exclude coding, QA, release orchestration, and complex multi-agent coordination from v1.",
            "Narrowing scope to PM proves core value before expanding system surface area.",
        ),
    }
    return mapping.get(
        category,
        (
            "Provide a concrete answer that improves planning quality and implementation clarity.",
            "Each answer should reduce ambiguity for downstream execution.",
        ),
    )


def generate_autonomous_answer(
    question: ClarifyingQuestion, persona: ExpertPersona
) -> AutonomousAnswer:
    answer, reasoning = _default_answer_for_category(question.category)
    return AutonomousAnswer(
        question_id=question.id,
        question=question.text,
        answer=answer,
        answered_by=persona,
        reasoning=reasoning,
    )
