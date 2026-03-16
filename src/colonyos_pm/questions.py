from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import ClarifyingQuestion
from colonyos_pm.prompts import QUESTION_GENERATION_SYSTEM


def generate_clarifying_questions(prompt: str) -> list[ClarifyingQuestion]:
    data = chat_json(
        system=QUESTION_GENERATION_SYSTEM,
        user=f"Feature request:\n\n{prompt}",
        temperature=0.5,
        max_tokens=1200,
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
