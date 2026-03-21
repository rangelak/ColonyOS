"""Intent Router Agent for ColonyOS.

This module provides a lightweight, cheap classifier that runs before the main
pipeline to determine the user's intent and route their query to the appropriate
handler:
- CODE_CHANGE: Full pipeline for code changes
- QUESTION: Direct answers using a read-only Q&A agent
- STATUS: Redirect to existing CLI commands
- OUT_OF_SCOPE: Polite rejection with suggestion

The router uses a single-turn haiku call with no tool access to minimize cost
and latency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from colonyos.sanitize import sanitize_untrusted_content

logger = logging.getLogger(__name__)

# Path to the Q&A instruction template
_QA_TEMPLATE_PATH = Path(__file__).parent / "instructions" / "qa.md"

# Default budget for Q&A answers (can be overridden via config)
DEFAULT_QA_BUDGET = 0.50


class RouterCategory(str, Enum):
    """Intent categories for user queries.

    CODE_CHANGE: Feature requests, bug fixes, refactoring → runs full pipeline
    QUESTION: Codebase inquiries, how-to questions → answers directly
    STATUS: Queue state, run history, stats → redirects to existing CLI commands
    OUT_OF_SCOPE: Unrelated requests → polite rejection with suggestion
    """

    CODE_CHANGE = "code_change"
    QUESTION = "question"
    STATUS = "status"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class RouterResult:
    """Structured output of the router classification.

    Attributes:
        category: The classified intent category.
        confidence: Confidence score between 0.0 and 1.0.
        summary: Brief description of what the user wants.
        reasoning: Explanation for the classification.
        suggested_command: For STATUS category, the CLI command to suggest.
    """

    category: RouterCategory
    confidence: float
    summary: str
    reasoning: str
    suggested_command: str | None = None


def _build_router_prompt(
    query: str,
    *,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    vision: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for the router LLM call.

    Returns (system_prompt, user_prompt).
    """
    system_parts: list[str] = [
        "You are an intent router for an autonomous coding system. "
        "Your job is to classify incoming user queries into one of four categories "
        "so the system can handle them appropriately.",
        "",
        "You must respond with ONLY a JSON object (no markdown fencing, no extra text) "
        "with these exact fields:",
        '  {"category": str, "confidence": float (0.0-1.0), '
        '"summary": str, "reasoning": str, "suggested_command": str|null}',
        "",
        "Categories:",
        "",
        "1. **code_change** — Feature requests, bug fixes, refactoring, or any request "
        "that requires modifying code. Examples:",
        '   - "Add a health check endpoint"',
        '   - "Fix the login bug"',
        '   - "Refactor the database module"',
        '   - "Update the API to support pagination"',
        "",
        "2. **question** — Questions about the codebase, how things work, or requesting "
        "explanations. These do NOT require code changes. Examples:",
        '   - "What does the sanitize function do?"',
        '   - "How does authentication work in this project?"',
        '   - "Explain the data flow in the API"',
        '   - "Where is the database connection configured?"',
        "",
        "3. **status** — Queries about queue state, run history, statistics, or system "
        "status. For these, include a `suggested_command` field. Examples:",
        '   - "Show me the queue status" → suggested_command: "colonyos status"',
        '   - "What runs have been completed?" → suggested_command: "colonyos stats"',
        '   - "Show me run details" → suggested_command: "colonyos show <run_id>"',
        "",
        "4. **out_of_scope** — Requests unrelated to coding or the project. Examples:",
        '   - "What is the weather today?"',
        '   - "Write me a poem"',
        '   - "Tell me a joke"',
        "",
        "Rules:",
        "- When uncertain between code_change and question, lean toward code_change "
        "(fail-open behavior).",
        "- confidence should reflect how certain you are about the classification.",
        "- summary should be a concise (1-2 sentence) description of what the user wants.",
        "- suggested_command is only required for status category.",
    ]

    if project_name:
        system_parts.append(f"\nProject: {project_name}")
    if project_description:
        system_parts.append(f"Description: {project_description}")
    if project_stack:
        system_parts.append(f"Stack: {project_stack}")
    if vision:
        system_parts.append(f"Vision: {vision}")

    safe_text = sanitize_untrusted_content(query)
    user_prompt = f"Classify this user query:\n\n{safe_text}"

    return "\n".join(system_parts), user_prompt


def _parse_router_response(raw_text: str) -> RouterResult:
    """Parse the LLM response into a RouterResult.

    Handles both clean JSON and JSON wrapped in markdown fences.
    Falls back to CODE_CHANGE on parse failure (fail-open).
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse router response as JSON: %s", text[:200])
        return RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.0,
            summary="",
            reasoning=f"Failed to parse router response: {text[:200]}",
        )

    # Parse and validate category
    raw_category = data.get("category", "code_change")
    try:
        category = RouterCategory(raw_category)
    except ValueError:
        logger.warning("Unknown router category '%s', defaulting to CODE_CHANGE", raw_category)
        return RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.0,
            summary=str(data.get("summary", "")),
            reasoning=f"Unknown category '{raw_category}', treating as code_change",
        )

    # Clamp confidence to [0.0, 1.0]
    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

    return RouterResult(
        category=category,
        confidence=confidence,
        summary=str(data.get("summary", "")),
        reasoning=str(data.get("reasoning", "")),
        suggested_command=data.get("suggested_command") or None,
    )


def route_query(
    query: str,
    *,
    repo_root: Path | None = None,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    vision: str = "",
    source: str = "cli",
) -> RouterResult:
    """Run the LLM-based intent router on a user query.

    Uses a single-turn haiku call with no tool access to minimize cost
    and prompt injection blast radius.

    Args:
        query: The user's input query to classify.
        repo_root: Repository root directory. Falls back to cwd if not provided.
        project_name: Name of the project for context.
        project_description: Brief description of the project.
        project_stack: Technology stack of the project.
        vision: Project vision statement.
        source: Origin of the query (cli, repl, slack) for logging.

    Returns:
        RouterResult with the classification.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase

    cwd = repo_root if repo_root is not None else Path.cwd()

    system, user = _build_router_prompt(
        query,
        project_name=project_name,
        project_description=project_description,
        project_stack=project_stack,
        vision=vision,
    )

    result = run_phase_sync(
        Phase.TRIAGE,
        user,
        cwd=cwd,
        system_prompt=system,
        model="haiku",
        budget_usd=0.05,  # tiny budget for routing
        allowed_tools=[],  # no tool access
    )

    raw_text = ""
    if result.artifacts:
        raw_text = next(iter(result.artifacts.values()), "")
    if not raw_text and result.error:
        logger.warning("Router LLM call failed: %s", result.error[:200])
        return RouterResult(
            category=RouterCategory.CODE_CHANGE,
            confidence=0.0,
            summary="",
            reasoning=f"Router call failed: {result.error[:200]}",
        )

    parsed = _parse_router_response(raw_text)

    logger.debug(
        "Router classified query from %s as %s (confidence=%.2f): %s",
        source,
        parsed.category.value,
        parsed.confidence,
        parsed.summary,
    )

    return parsed


def _build_qa_prompt(
    question: str,
    *,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for the Q&A agent.

    Loads the qa.md template and injects project context.

    Returns (system_prompt, user_prompt).
    """
    # Load the Q&A template
    if _QA_TEMPLATE_PATH.exists():
        template = _QA_TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        # Fallback if template is missing
        logger.warning("Q&A template not found at %s, using fallback", _QA_TEMPLATE_PATH)
        template = (
            "You are a read-only codebase assistant. "
            "Answer questions about the code using only Read, Glob, and Grep tools. "
            "Do not modify any files or execute commands."
        )

    system_parts: list[str] = [template]

    # Add project context if available
    if project_name:
        system_parts.append(f"\n## Project Context\n\nProject: {project_name}")
    if project_description:
        system_parts.append(f"Description: {project_description}")
    if project_stack:
        system_parts.append(f"Stack: {project_stack}")

    safe_question = sanitize_untrusted_content(question)
    user_prompt = f"Please answer this question about the codebase:\n\n{safe_question}"

    return "\n".join(system_parts), user_prompt


def answer_question(
    question: str,
    *,
    repo_root: Path | None = None,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    model: str = "haiku",
    qa_budget: float = DEFAULT_QA_BUDGET,
) -> str:
    """Answer a question about the codebase using a read-only Q&A agent.

    This function spawns an LLM agent with read-only tools (Read, Glob, Grep)
    to explore the codebase and answer the user's question.

    Args:
        question: The user's question about the codebase.
        repo_root: Repository root directory. Falls back to cwd if not provided.
        project_name: Name of the project for context.
        project_description: Brief description of the project.
        project_stack: Technology stack of the project.
        model: Model to use for answering (default: haiku).
        qa_budget: Budget cap for the Q&A call (default: $0.50).

    Returns:
        The answer as a string, or an error message if the call failed.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase

    cwd = repo_root if repo_root is not None else Path.cwd()

    system, user = _build_qa_prompt(
        question,
        project_name=project_name,
        project_description=project_description,
        project_stack=project_stack,
    )

    # Read-only tools only - no Write, Edit, Bash, etc.
    read_only_tools = ["Read", "Glob", "Grep"]

    result = run_phase_sync(
        Phase.QA,
        user,
        cwd=cwd,
        system_prompt=system,
        model=model,
        budget_usd=qa_budget,
        allowed_tools=read_only_tools,
    )

    # Extract the answer from the result
    if result.artifacts:
        answer = next(iter(result.artifacts.values()), "")
        if answer:
            return answer

    if result.error:
        logger.warning("Q&A agent call failed: %s", result.error[:200])
        return f"I was unable to answer your question due to an error: {result.error[:200]}"

    return "I was unable to find an answer to your question."
