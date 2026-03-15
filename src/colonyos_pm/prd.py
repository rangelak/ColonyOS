from __future__ import annotations

from colonyos_pm.models import AutonomousAnswer


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def build_prd_markdown(prompt: str, answers: list[AutonomousAnswer]) -> str:
    answer_map = {answer.question_id: answer for answer in answers}

    goals = [
        "Generate a high-quality PRD autonomously from rough prompts.",
        "Reduce implementation ambiguity before coding begins.",
        "Provide a deterministic handoff package for task generation.",
    ]
    user_stories = [
        "As a founder/operator, I want to submit rough ideas and receive implementation-ready PRDs.",
        "As a coding agent, I want clear and explicit requirements to improve first-pass success.",
        "As a future task agent, I want predictable PRD structure for deterministic task derivation.",
    ]
    functional_requirements = [
        "The system must accept an initial feature prompt.",
        "The system must generate clarifying questions and autonomous answers.",
        "The system must select and record expert personas per answer.",
        "The system must output a PRD with explicit sections suitable for a junior developer.",
        "The system must classify risk and determine escalation behavior.",
        "The system must emit handoff metadata for downstream task generation.",
        "Downstream implementation tasks must include a tests-first step before code changes.",
    ]

    qa_block = []
    for idx, answer in enumerate(answers, start=1):
        qa_block.append(f"### {idx}. {answer.question}")
        qa_block.append(f"**Answer:** {answer.answer}")
        qa_block.append(f"**Answered by:** {answer.answered_by.value}")
        qa_block.append(f"**Reasoning:** {answer.reasoning}")
        qa_block.append("")

    return "\n".join(
        [
            "# PRD: Autonomous PM Workflow",
            "",
            "## Clarifying Questions And Autonomous Answers",
            "",
            *qa_block,
            "## Introduction/Overview",
            "",
            f"This PRD was generated from the following prompt: {prompt}",
            "The workflow reduces ambiguity before coding by creating clarifying questions, answering them autonomously with expert personas, and assembling a deterministic planning artifact.",
            "",
            "## Goals",
            "",
            _bullets(goals),
            "",
            "## User Stories",
            "",
            _bullets(user_stories),
            "",
            "## Functional Requirements",
            "",
            "\n".join(
                f"{idx}. {requirement}"
                for idx, requirement in enumerate(functional_requirements, start=1)
            ),
            "",
            "## Non-Goals (Out of Scope)",
            "",
            _bullets(
                [
                    "Coding-agent implementation details.",
                    "Full orchestration backend implementation in v1.",
                    "Human-heavy approval loops as default behavior.",
                ]
            ),
            "",
            "## Design Considerations",
            "",
            _bullets(
                [
                    "Keep outputs readable and concrete for junior developers.",
                    "Expose enough reasoning to build trust without excessive verbosity.",
                    "Keep persona selection intentional and tied to question category.",
                ]
            ),
            "",
            "## Technical Considerations",
            "",
            _bullets(
                [
                    "Follow create_prd rule structure for output consistency.",
                    "Emit deterministic metadata for generate_tasks handoff.",
                    "Enforce tests-first sequencing in downstream task generation.",
                    "Treat generated planning artifacts as operational outputs.",
                ]
            ),
            "",
            "## Success Metrics",
            "",
            _bullets(
                [
                    "Higher first-pass implementation quality from coding agents.",
                    "Reduced ambiguous implementation requests.",
                    "Faster spec-to-code cycle time.",
                ]
            ),
            "",
            "## Open Questions",
            "",
            _bullets(
                [
                    "What exact risk taxonomy thresholds should be used in production?",
                    "How much planning trace should be user-visible by default?",
                    "What final data model will back Supabase storage?",
                ]
            ),
            "",
            f"<!-- answers_included={len(answer_map)} -->",
        ]
    )
