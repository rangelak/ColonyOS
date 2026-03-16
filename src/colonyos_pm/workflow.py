from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1

from colonyos_pm.answers import generate_autonomous_answer
from colonyos_pm.models import HandoffPayload, WorkflowArtifacts
from colonyos_pm.personas import select_persona
from colonyos_pm.prd import build_prd_markdown
from colonyos_pm.questions import generate_clarifying_questions
from colonyos_pm.risk import assess_risk

MAX_PARALLEL_ANSWER_CALLS = 4


def _build_work_id(prompt: str) -> str:
    digest = sha1(prompt.strip().encode("utf-8")).hexdigest()[:10]
    return f"pmw-{digest}"


def _log(msg: str) -> None:
    print(f"[pm-workflow] {msg}", file=sys.stderr, flush=True)


def _parallel_answer_workers(question_count: int) -> int:
    return max(1, min(MAX_PARALLEL_ANSWER_CALLS, question_count))


def run_pm_workflow(prompt: str) -> WorkflowArtifacts:
    _log("Generating clarifying questions...")
    with ThreadPoolExecutor(max_workers=2) as planning_executor:
        question_future = planning_executor.submit(generate_clarifying_questions, prompt)
        risk_future = planning_executor.submit(assess_risk, prompt)

        questions = question_future.result()
        _log(f"  Generated {len(questions)} questions.")

        _log("Generating autonomous answers with expert personas...")
        with ThreadPoolExecutor(
            max_workers=_parallel_answer_workers(len(questions))
        ) as answer_executor:
            answer_futures = []
            for question in questions:
                persona = select_persona(question)
                _log(f"  [{persona.value}] answering: {question.text[:80]}...")
                answer_futures.append(
                    answer_executor.submit(generate_autonomous_answer, question, persona)
                )
            answers = [future.result() for future in answer_futures]

        risk = risk_future.result()
    _log(f"  Answered {len(answers)} questions.")

    _log("Assessing risk...")
    _log(f"  Risk tier: {risk.tier.value} (score={risk.score}, escalate={risk.escalate_to_human})")

    _log("Building PRD from Q&A output...")
    prd_markdown = build_prd_markdown(prompt=prompt, answers=answers)
    _log(f"  PRD generated ({len(prd_markdown)} chars).")

    work_id = _build_work_id(prompt)
    handoff = HandoffPayload(
        target_flow="generate_tasks",
        source_artifact="create_prd",
        metadata={
            "work_id": work_id,
            "risk_tier": risk.tier.value,
            "escalate_to_human": str(risk.escalate_to_human).lower(),
            "prd_format": "markdown",
            "execution_policy": "tests_first",
        },
    )

    internal_trace = {
        "question_count": len(questions),
        "persona_distribution": {
            persona.value: len(
                [a for a in answers if a.answered_by.value == persona.value]
            )
            for persona in {a.answered_by for a in answers}
        },
        "visibility": {
            "user_visible": ["prompt", "clarifying_questions", "answers", "prd_markdown"],
            "internal_only": ["risk_score", "persona_distribution", "handoff_metadata"],
        },
        "v1_boundaries": [
            "No coding-agent execution",
            "No QA/release orchestration",
            "No full validation engine",
        ],
    }

    _log("Workflow complete.")
    return WorkflowArtifacts(
        work_id=work_id,
        prompt=prompt,
        clarifying_questions=questions,
        autonomous_answers=answers,
        risk_assessment=risk,
        prd_markdown=prd_markdown,
        handoff_payload=handoff,
        internal_trace=internal_trace,
    )
