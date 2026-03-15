from __future__ import annotations

from colonyos_pm.llm import chat
from colonyos_pm.models import AutonomousAnswer

PRD_SYSTEM_PROMPT = """\
You are a world-class product manager writing a PRD for a junior developer audience.

You will receive:
1. The original feature request / prompt.
2. A set of clarifying questions and their autonomous answers (including which expert persona answered and their reasoning).

Your job is to synthesize all of that into a complete, high-quality PRD in Markdown.

The PRD MUST include these sections in this order:
1. # PRD: <concise feature title>
2. ## Clarifying Questions And Autonomous Answers
   - Reproduce every Q&A with the answering persona and reasoning.
3. ## Introduction/Overview
4. ## Goals
5. ## User Stories
6. ## Functional Requirements (numbered list)
7. ## Non-Goals (Out of Scope)
8. ## Design Considerations
9. ## Technical Considerations
10. ## Success Metrics
11. ## Open Questions

Rules:
- Be explicit and unambiguous. A junior developer should be able to read this and understand what to build.
- Functional requirements must be numbered and use "The system must..." language.
- Include a requirement that downstream implementation tasks must follow a tests-first approach.
- Do NOT include implementation details or code snippets.
- Keep it under 3000 words.
- Output raw Markdown only, no code fences wrapping the document.
"""


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
        system=PRD_SYSTEM_PROMPT,
        user=user_message,
        temperature=0.5,
        max_tokens=4096,
    )
