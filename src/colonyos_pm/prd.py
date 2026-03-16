from __future__ import annotations

from colonyos_pm.llm import chat
from colonyos_pm.models import AutonomousAnswer
from colonyos_pm.prompts import PRD_ASSEMBLY_SYSTEM


def build_prd_markdown(prompt: str, answers: list[AutonomousAnswer]) -> str:
    qa_block = []
    for idx, a in enumerate(answers, start=1):
        qa_block.append(f"### {idx}. {a.question}")
        qa_block.append(f"**Answer:** {a.answer}")
        qa_block.append(f"**Answered by:** {a.answered_by.value}")
        qa_block.append(f"**Reasoning:** {a.reasoning}")
        qa_block.append("")

    user_message = (
        f"## Original Prompt\n\n{prompt}\n\n"
        f"## Clarifying Questions & Answers\n\n" + "\n".join(qa_block)
    )

    return chat(
        system=PRD_ASSEMBLY_SYSTEM,
        user=user_message,
        temperature=0.5,
        max_tokens=4096,
    )
