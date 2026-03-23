"""Intent Router Agent for ColonyOS.

This module provides a lightweight, cheap classifier that runs before the main
pipeline to determine the user's intent and route their query to the appropriate
handler:
- CODE_CHANGE: Full pipeline for code changes
- QUESTION: Direct answers using a read-only Q&A agent
- WORKFLOW: Git ops, shell commands, DevOps tasks via a full-power agent
- STATUS: Redirect to existing CLI commands
- OUT_OF_SCOPE: Polite rejection with suggestion

The router uses a single-turn call with no tool access to classify intent.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from colonyos.sanitize import sanitize_untrusted_content

logger = logging.getLogger(__name__)

# Path to instruction templates
_QA_TEMPLATE_PATH = Path(__file__).parent / "instructions" / "qa.md"
_WORKFLOW_TEMPLATE_PATH = Path(__file__).parent / "instructions" / "workflow.md"

# Default budgets (can be overridden via config)
DEFAULT_QA_BUDGET = 0.50
DEFAULT_WORKFLOW_BUDGET = 1.00


class RouterCategory(str, Enum):
    """Intent categories for user queries.

    CODE_CHANGE: Feature requests, bug fixes, refactoring → runs full pipeline
    QUESTION: Codebase inquiries, how-to questions → answers directly
    WORKFLOW: Git ops, shell commands, DevOps tasks → lightweight agent with full tools
    STATUS: Queue state, run history, stats → redirects to existing CLI commands
    OUT_OF_SCOPE: Unrelated requests → polite rejection with suggestion
    """

    CODE_CHANGE = "code_change"
    QUESTION = "question"
    WORKFLOW = "workflow"
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
        "Your job is to classify incoming user queries into one of five categories "
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
        "that requires *designing and building* new functionality. These go through a full "
        "plan → implement → review pipeline. Examples:",
        '   - "Add a health check endpoint"',
        '   - "Fix the login bug"',
        '   - "Refactor the database module"',
        '   - "Update the API to support pagination"',
        "",
        "2. **workflow** — Git operations, shell commands, DevOps tasks, or developer "
        "workflow actions that can be executed directly without a planning/review pipeline. "
        "These are quick, concrete actions the user wants done right now. Examples:",
        '   - "Commit my changes and push"',
        '   - "Create a new branch called feature-x"',
        '   - "Run the tests"',
        '   - "Show me the git log"',
        '   - "Update dependencies"',
        '   - "Rebase onto main"',
        '   - "Squash the last 3 commits"',
        "",
        "3. **question** — Questions about the codebase, how things work, or requesting "
        "explanations. These do NOT require code changes. Examples:",
        '   - "What does the sanitize function do?"',
        '   - "How does authentication work in this project?"',
        '   - "Explain the data flow in the API"',
        '   - "Where is the database connection configured?"',
        "",
        "4. **status** — Queries about queue state, run history, statistics, or system "
        "status. For these, include a `suggested_command` field. Examples:",
        '   - "Show me the queue status" → suggested_command: "colonyos status"',
        '   - "What runs have been completed?" → suggested_command: "colonyos stats"',
        '   - "Show me run details" → suggested_command: "colonyos show <run_id>"',
        "",
        "5. **out_of_scope** — Requests unrelated to coding or the project. Examples:",
        '   - "What is the weather today?"',
        '   - "Write me a poem"',
        '   - "Tell me a joke"',
        "",
        "Rules:",
        "- **workflow vs code_change**: If the user is asking to *execute a concrete "
        "command or action* (git, shell, deploy, run tests, commit), classify as workflow. "
        "If they are asking to *design and build a feature or fix a bug*, classify as "
        "code_change. When the request is imperative and could be done with a few shell "
        "commands, prefer workflow.",
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
    model: str = "opus",
) -> RouterResult:
    """Run the LLM-based intent router on a user query.

    Uses a single-turn call with no tool access to classify intent.

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
        model=model,
        budget_usd=0.05,  # tiny budget for routing
        allowed_tools=[],  # no tool access
    )

    # Extract text from artifacts. run_phase_sync returns a single-entry dict
    # keyed by artifact name; we take the first (and only) value. If the SDK
    # ever returns multiple artifacts, revisit to use a well-known key.
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
    model: str = "opus",
    qa_budget: float = DEFAULT_QA_BUDGET,
) -> tuple[str, float]:
    """Answer a question about the codebase using a read-only Q&A agent.

    This function spawns an LLM agent with read-only tools (Read, Glob, Grep)
    to explore the codebase and answer the user's question.

    Returns:
        ``(answer_text, cost_usd)`` tuple.
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

    cost = result.cost_usd or 0.0

    if result.artifacts:
        answer = next(iter(result.artifacts.values()), "")
        if answer:
            return answer, cost

    if result.error:
        logger.warning("Q&A agent call failed: %s", result.error[:200])
        return f"I was unable to answer your question due to an error: {result.error[:200]}", cost

    return "I was unable to find an answer to your question.", cost


def _build_workflow_prompt(
    request: str,
    *,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for the workflow agent.

    Returns (system_prompt, user_prompt).
    """
    if _WORKFLOW_TEMPLATE_PATH.exists():
        template = _WORKFLOW_TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        logger.warning("Workflow template not found at %s, using fallback", _WORKFLOW_TEMPLATE_PATH)
        template = (
            "You are a developer workflow assistant with full tool access. "
            "Execute the user's request directly using Bash, Read, Write, Edit, Glob, and Grep."
        )

    context_parts: list[str] = [template]
    if project_name:
        context_parts.append(f"\n## Project Context\n\nProject: {project_name}")
    if project_description:
        context_parts.append(f"Description: {project_description}")
    if project_stack:
        context_parts.append(f"Stack: {project_stack}")

    system_prompt = "\n".join(context_parts)
    user_prompt = sanitize_untrusted_content(request)
    return system_prompt, user_prompt


def run_workflow(
    request: str,
    *,
    repo_root: Path | None = None,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    model: str = "opus",
    workflow_budget: float = DEFAULT_WORKFLOW_BUDGET,
) -> tuple[str, float]:
    """Execute a developer workflow action using a full-power agent.

    Spawns an LLM agent with all tools (Bash, Read, Write, Edit, Glob, Grep)
    to handle git operations, shell commands, and other developer tasks.

    Returns:
        ``(output_text, cost_usd)`` tuple.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase

    cwd = repo_root if repo_root is not None else Path.cwd()

    system, user = _build_workflow_prompt(
        request,
        project_name=project_name,
        project_description=project_description,
        project_stack=project_stack,
    )

    all_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

    result = run_phase_sync(
        Phase.WORKFLOW,
        user,
        cwd=cwd,
        system_prompt=system,
        model=model,
        budget_usd=workflow_budget,
        allowed_tools=all_tools,
    )

    cost = result.cost_usd or 0.0

    if result.artifacts:
        answer = next(iter(result.artifacts.values()), "")
        if answer:
            return answer, cost

    if result.error:
        logger.warning("Workflow agent call failed: %s", result.error[:200])
        return f"Workflow action failed: {result.error[:200]}", cost

    return "Workflow action completed (no output).", cost


def log_router_decision(
    *,
    repo_root: Path,
    prompt: str,
    result: RouterResult,
    source: str = "cli",
) -> Path | None:
    """Log a routing decision to the audit trail.

    Writes a JSON file to ``.colonyos/runs/triage_<timestamp>.json``
    containing the prompt (sanitized), classification result, confidence,
    reasoning, source, and timestamp.

    Args:
        repo_root: Repository root directory.
        prompt: The original user prompt (will be sanitized before logging).
        result: The RouterResult from classification.
        source: Origin of the query (cli, repl, slack).

    Returns:
        Path to the written log file, or None if writing failed.
    """
    runs_dir = repo_root / ".colonyos" / "runs"
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Failed to create runs directory: %s", runs_dir)
        return None

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    log_path = runs_dir / f"triage_{timestamp}.json"

    safe_prompt = sanitize_untrusted_content(prompt)

    log_data = {
        "timestamp": now.isoformat(),
        "source": source,
        "prompt": safe_prompt,
        "category": result.category.value,
        "confidence": result.confidence,
        "summary": result.summary,
        "reasoning": result.reasoning,
        "suggested_command": result.suggested_command,
    }

    try:
        log_path.write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Router decision logged to %s", log_path)
        return log_path
    except OSError:
        logger.warning("Failed to write router decision log: %s", log_path)
        return None
