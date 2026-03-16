from __future__ import annotations

import re

from colonyos_pm.llm import chat
from colonyos_pm.models import AutonomousAnswer
from colonyos_pm.prompts import PRD_ASSEMBLY_SYSTEM


def _normalize_task_prd_format(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    in_qa_section = False
    separator_inserted = False

    for line in lines:
        stripped = line.strip()

        if stripped == "## Clarifying Questions And Autonomous Answers":
            in_qa_section = True

        if in_qa_section and stripped == "## Introduction/Overview" and not separator_inserted:
            if output and output[-1] != "":
                output.append("")
            output.append("---")
            output.append("")
            separator_inserted = True
            in_qa_section = False

        if stripped.startswith("- Answer:"):
            output.append(f"**Answer:** {stripped.removeprefix('- Answer:').strip()}")
            output.append("")
            continue

        if stripped.startswith("- Answered by:"):
            output.append(
                f"**Answered by:** {stripped.removeprefix('- Answered by:').strip()}"
            )
            output.append("")
            continue

        if stripped.startswith("- Reasoning:"):
            output.append(
                f"**Reasoning:** {stripped.removeprefix('- Reasoning:').strip()}"
            )
            output.append("")
            continue

        output.append(line)

    normalized = "\n".join(output)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized + "\n"


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

    raw_markdown = chat(
        system=PRD_ASSEMBLY_SYSTEM,
        user=user_message,
        temperature=0.5,
        max_tokens=None,
    )
    return _normalize_task_prd_format(raw_markdown)
