from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import ClarifyingQuestion

SYSTEM_PROMPT = """\
You are a world-class product manager. Given a rough feature request, generate \
8-12 high-value clarifying questions that a senior PM would ask before writing \
a PRD. Each question must probe a specific dimension: goal, users, scope, \
artifact, autonomy, quality, handoff, validation, risk, design, or technical.

Return JSON with this exact schema:
{
  "questions": [
    {"id": "q1", "category": "<dimension>", "text": "<question>"},
    ...
  ]
}

Rules:
- Questions must be concrete and opinionated, not generic filler.
- Each question must target a different dimension of the problem.
- Questions should expose hidden assumptions and force explicit trade-offs.
- Keep the total between 8 and 12 questions.
"""


def generate_clarifying_questions(prompt: str) -> list[ClarifyingQuestion]:
    data = chat_json(
        system=SYSTEM_PROMPT,
        user=f"Feature request:\n\n{prompt}",
        temperature=0.5,
    )
    raw_questions = data.get("questions", []) if isinstance(data, dict) else []
    return [
        ClarifyingQuestion(
            id=q.get("id", f"q{i}"),
            text=q["text"],
            category=q.get("category", "general"),
        )
        for i, q in enumerate(raw_questions, start=1)
        if "text" in q
    ]
