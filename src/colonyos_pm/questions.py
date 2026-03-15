from __future__ import annotations

from colonyos_pm.models import ClarifyingQuestion


BASE_QUESTIONS: list[tuple[str, str]] = [
    (
        "goal",
        "What is the primary business outcome this workflow should optimize for first?",
    ),
    ("users", "Who are the primary and secondary users for this feature?"),
    (
        "artifact",
        "What is the exact output artifact this workflow must produce in v1?",
    ),
    (
        "autonomy",
        "How autonomous should clarification be before any human is involved?",
    ),
    (
        "quality",
        "What quality bar should generated artifacts meet before handoff?",
    ),
    (
        "handoff",
        "What should happen immediately after PRD generation in the pipeline?",
    ),
    (
        "validation",
        "What minimum validation should run before handing work to coding agents?",
    ),
    (
        "risk",
        "How should the system classify risk and decide escalation thresholds?",
    ),
]


def generate_clarifying_questions(prompt: str, max_questions: int = 10) -> list[ClarifyingQuestion]:
    """Generate bounded, deterministic clarifying questions for weak prompts."""
    normalized = prompt.strip()
    questions = [
        ClarifyingQuestion(id=f"q{i + 1}", text=text, category=category)
        for i, (category, text) in enumerate(BASE_QUESTIONS)
    ]
    if len(normalized.split()) < 10:
        questions.append(
            ClarifyingQuestion(
                id=f"q{len(questions) + 1}",
                category="scope",
                text="What should explicitly be out of scope for v1 to avoid overreach?",
            )
        )
    return questions[:max(4, min(max_questions, 12))]
