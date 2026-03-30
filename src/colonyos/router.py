"""Routing helpers for lightweight mode selection and codebase Q&A.

This module contains two related capabilities:

1. A low-cost mode selector that chooses how the TUI should handle a user
   request (direct work, plan/implement loop, continue existing artifacts,
   review-only, cleanup, or fallback).
2. A read-only Q&A helper for codebase questions.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from colonyos.models import extract_result_text
from colonyos.sanitize import sanitize_display_text, sanitize_untrusted_content

logger = logging.getLogger(__name__)


def _sanitize_metadata(text: str) -> str:
    """Sanitize project metadata for safe inclusion in prompts.

    Applies both display-level sanitization (ANSI/control char removal)
    and content-level sanitization (XML tag stripping) for defense-in-depth.
    """
    return sanitize_untrusted_content(sanitize_display_text(text))

# Path to the Q&A instruction template
_QA_TEMPLATE_PATH = Path(__file__).parent / "instructions" / "qa.md"

# Path to the shared base instruction template
_BASE_TEMPLATE_PATH = Path(__file__).parent / "instructions" / "base.md"

# Default budget for Q&A answers (can be overridden via config)
DEFAULT_QA_BUDGET = 0.50


class ModeAgentMode(str, Enum):
    """Execution modes the default TUI agent can choose from."""

    DIRECT_AGENT = "direct_agent"
    PLAN_IMPLEMENT_LOOP = "plan_implement_loop"
    IMPLEMENT_ONLY = "implement_only"
    REVIEW_ONLY = "review_only"
    CLEANUP_LOOP = "cleanup_loop"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class ModeAgentDecision:
    """Structured result from the mode-selection agent."""

    mode: ModeAgentMode
    confidence: float
    summary: str
    reasoning: str
    announcement: str
    skip_planning: bool = False


def _is_cleanup_request(lowered: str) -> bool:
    """Return True only for explicit cleanup workflow requests.

    Avoid hijacking pasted diagnostic text that merely mentions the word
    "cleanup" while describing some other failure.
    """
    return (
        lowered.startswith("cleanup")
        or lowered.startswith("clean up")
        or lowered.startswith("repo hygiene")
        or lowered.startswith("code hygiene")
        or " cleanup the " in f" {lowered} "
        or " clean up the " in f" {lowered} "
        or " hygiene for " in f" {lowered} "
    )


def _has_explicit_workflow_intent(lowered: str) -> bool:
    """Return True when the request clearly wants a non-direct workflow."""
    if any(phrase in lowered for phrase in (
        "continue the last plan",
        "continue from the last",
        "continue existing",
        "use the latest prd",
        "continue from prd",
        "continue from tasks",
    )):
        return True
    if lowered.startswith("review ") or " just review" in lowered or "review this branch" in lowered:
        return True
    if _is_cleanup_request(lowered):
        return True
    return any(re.search(pat, lowered) for pat in (
        r"\badd\b(?!\s+(?:a note|me to|more context))",
        r"\bbuild\b",
        r"\bimplement\b",
        r"\bfeature\b",
        r"\brefactor\b",
        r"\bintroduce\b",
        r"\bcreate\b",
    ))


def _looks_like_direct_followup(lowered: str) -> bool:
    """Heuristic for short continuation turns in an active direct thread."""
    if not lowered or _has_explicit_workflow_intent(lowered):
        return False

    words = [part for part in re.split(r"\s+", lowered) if part]
    if not words:
        return False
    if len(words) <= 12:
        return True
    if any(phrase in lowered for phrase in (
        "go ahead",
        "do it",
        "use that",
        "ship it",
        "sounds good",
        "that works",
        "please",
    )) and len(words) <= 18:
        return True
    return False


def _heuristic_mode_decision(
    query: str,
    *,
    continuation_active: bool = False,
) -> ModeAgentDecision | None:
    """Use cheap keyword heuristics for obvious requests before invoking a model."""
    lowered = sanitize_untrusted_content(query).strip().lower()
    if not lowered:
        return ModeAgentDecision(
            mode=ModeAgentMode.FALLBACK,
            confidence=1.0,
            summary="Empty request",
            reasoning="The request is empty after sanitization.",
            announcement="I need a bit more direction.",
        )

    if continuation_active and _looks_like_direct_followup(lowered):
        return ModeAgentDecision(
            mode=ModeAgentMode.DIRECT_AGENT,
            confidence=0.99,
            summary="Continue active direct conversation",
            reasoning="A direct-agent session is already active and this looks like a short follow-up.",
            announcement="Continuing conversation.",
        )

    if any(phrase in lowered for phrase in (
        "continue the last plan",
        "continue from the last",
        "continue existing",
        "use the latest prd",
        "continue from prd",
        "continue from tasks",
    )):
        return ModeAgentDecision(
            mode=ModeAgentMode.IMPLEMENT_ONLY,
            confidence=0.98,
            summary="Continue existing planned work",
            reasoning="The user explicitly asked to continue from existing artifacts.",
            announcement="Continuing from the latest planned work.",
        )

    if lowered.startswith("review ") or " just review" in lowered or "review this branch" in lowered:
        return ModeAgentDecision(
            mode=ModeAgentMode.REVIEW_ONLY,
            confidence=0.97,
            summary="Review existing code",
            reasoning="The request explicitly asks for review-only behavior.",
            announcement="Entering review mode.",
        )

    if _is_cleanup_request(lowered):
        return ModeAgentDecision(
            mode=ModeAgentMode.CLEANUP_LOOP,
            confidence=0.96,
            summary="Run cleanup workflow",
            reasoning="The request explicitly asks for cleanup or hygiene work.",
            announcement="Entering cleanup mode.",
        )

    if lowered.endswith("?") or lowered.startswith(("what ", "how ", "why ", "where ", "explain ")):
        return ModeAgentDecision(
            mode=ModeAgentMode.DIRECT_AGENT,
            confidence=0.94,
            summary="Answer directly",
            reasoning="This reads like a question or explanation request.",
            announcement="Handling this directly.",
        )

    # Use word-boundary matching to avoid false positives like "make sure"
    # or "change my mind". The pattern requires the keyword to appear as the
    # action verb at the start of a clause (beginning of string or after
    # punctuation/whitespace), NOT followed by common non-action continuations.
    _DIRECT_PATTERNS = (
        r"\bchange\b(?!\s+(?:my|your|the subject|my mind))",
        r"\bmake\b(?!\s+(?:sure|certain|sense|a note|it clear|up))",
        r"\brename\b",
        r"\bfix typo\b",
        r"\bsmall fix\b",
        r"\btiny fix\b",
    )
    if any(re.search(pat, lowered) for pat in _DIRECT_PATTERNS):
        return ModeAgentDecision(
            mode=ModeAgentMode.DIRECT_AGENT,
            confidence=0.9,
            summary="Small focused direct change",
            reasoning="This appears to be a small, localized request.",
            announcement="Handling this directly.",
        )

    _PIPELINE_PATTERNS = (
        r"\badd\b(?!\s+(?:a note|me to|more context))",
        r"\bbuild\b",
        r"\bimplement\b",
        r"\bfeature\b",
        r"\brefactor\b",
        r"\bintroduce\b",
        r"\bcreate\b",
    )
    if any(re.search(pat, lowered) for pat in _PIPELINE_PATTERNS):
        return ModeAgentDecision(
            mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP,
            confidence=0.92,
            summary="Feature work that should use the pipeline",
            reasoning="This appears to be larger implementation work.",
            announcement="Entering feature planning mode.",
        )

    return None


def _build_mode_selection_prompt(
    query: str,
    *,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    vision: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for the TUI mode-selection agent."""
    system_parts: list[str] = [
        "You are the default ColonyOS TUI mode-selection agent.",
        "Decide the lightest operating mode that should handle the user's request.",
        "This is an internal routing step, not a user-visible explanation.",
        "",
        "You must respond with ONLY a JSON object (no markdown fencing, no extra text)",
        "with these exact fields:",
        '  {"mode": str, "confidence": float, "summary": str, "reasoning": str, "announcement": str, "skip_planning": bool}',
        "",
        "Valid modes:",
        '- "direct_agent" — handle the request directly in the TUI using a general coding agent. Use for questions, explanations, status-like asks, tiny edits, and focused small requests.',
        '- "plan_implement_loop" — use the full structured pipeline for larger, ambiguous, or multi-step feature work.',
        '- "implement_only" — continue already-planned work from existing PRD/tasks artifacts.',
        '- "review_only" — review existing code without entering the planning pipeline.',
        '- "cleanup_loop" — run cleanup / hygiene / structural scan style workflows.',
        '- "fallback" — ask for clarification or decline when the request does not fit a supported coding flow.',
        "",
        "Rules:",
        "- Prefer direct_agent unless the request clearly needs a bigger workflow.",
        "- Use plan_implement_loop when the request sounds like a substantial feature, architecture change, or unclear multi-step implementation.",
        "- Use implement_only when the user explicitly asks to continue existing PRD/tasks work or resume from generated artifacts.",
        "- Use review_only when the user explicitly wants review or code critique.",
        "- Use cleanup_loop for cleanup, hygiene, scan, or refactor-maintenance requests.",
        "- Use fallback for clearly unrelated or too-unclear requests.",
        "- announcement must be a short plain-English sentence the TUI can show before the mode starts, for example: 'Entering feature planning mode.'",
        "- confidence should reflect certainty from 0.0 to 1.0.",
        "- summary should briefly describe the user's intent.",
        "- skip_planning should be true when mode is plan_implement_loop but the request is trivial or small (e.g., typo fix, rename, single-file tweak). Set false for larger or unclear work.",
    ]

    if project_name:
        system_parts.append(f"\nProject: {_sanitize_metadata(project_name)}")
    if project_description:
        system_parts.append(f"Description: {_sanitize_metadata(project_description)}")
    if project_stack:
        system_parts.append(f"Stack: {_sanitize_metadata(project_stack)}")
    if vision:
        system_parts.append(f"Vision: {_sanitize_metadata(vision)}")

    safe_text = sanitize_untrusted_content(query)
    user_prompt = f"Choose the best mode for this user request:\n\n{safe_text}"
    return "\n".join(system_parts), user_prompt


def _parse_mode_selection_response(raw_text: str) -> ModeAgentDecision:
    """Parse mode-selection JSON, falling back safely to the full pipeline."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    fallback = ModeAgentDecision(
        mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP,
        confidence=0.0,
        summary="",
        reasoning=f"Failed to parse mode selection response: {text[:200]}",
        announcement="Entering feature planning mode.",
    )

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse mode selection response as JSON: %s", text[:200])
        return fallback

    raw_mode = data.get("mode", ModeAgentMode.PLAN_IMPLEMENT_LOOP.value)
    try:
        mode = ModeAgentMode(raw_mode)
    except ValueError:
        logger.warning("Unknown mode '%s', defaulting to plan_implement_loop", raw_mode)
        return ModeAgentDecision(
            mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP,
            confidence=0.0,
            summary=str(data.get("summary", "")),
            reasoning=f"Unknown mode '{raw_mode}', treating as plan_implement_loop",
            announcement="Entering feature planning mode.",
        )

    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    announcement = str(data.get("announcement", "")).strip() or "Entering feature planning mode."
    skip_planning = bool(data.get("skip_planning", False))
    return ModeAgentDecision(
        mode=mode,
        confidence=confidence,
        summary=str(data.get("summary", "")),
        reasoning=str(data.get("reasoning", "")),
        announcement=announcement,
        skip_planning=skip_planning,
    )


def choose_tui_mode(
    query: str,
    *,
    repo_root: Path | None = None,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    vision: str = "",
    source: str = "tui",
    model: str | None = None,
    continuation_active: bool = False,
) -> ModeAgentDecision:
    """Select the best TUI operating mode for a user request."""
    from colonyos.agent import run_phase_sync
    from colonyos.config import RouterConfig, load_config
    from colonyos.models import Phase

    heuristic = _heuristic_mode_decision(
        query,
        continuation_active=continuation_active,
    )
    if heuristic is not None:
        logger.debug("Mode selector used heuristic decision: %s", heuristic.mode.value)
        return heuristic

    cwd = repo_root if repo_root is not None else Path.cwd()
    resolved_model = model
    if resolved_model is None:
        if repo_root is not None:
            resolved_model = load_config(repo_root).router.model
        else:
            resolved_model = RouterConfig().model

    system, user = _build_mode_selection_prompt(
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
        model=resolved_model,
        budget_usd=0.05,
        allowed_tools=[],
    )

    raw_text = extract_result_text(result.artifacts)
    if not raw_text and result.error:
        logger.warning("Mode-selection call failed from %s: %s", source, result.error[:200])
        return ModeAgentDecision(
            mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP,
            confidence=0.0,
            summary="",
            reasoning=f"Mode-selection call failed: {result.error[:200]}",
            announcement="Entering feature planning mode.",
        )

    parsed = _parse_mode_selection_response(raw_text)
    logger.debug(
        "Mode selector classified query from %s as %s (confidence=%.2f): %s",
        source,
        parsed.mode.value,
        parsed.confidence,
        parsed.summary,
    )
    return parsed


def _load_base_instruction() -> str:
    if _BASE_TEMPLATE_PATH.exists():
        return _BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        "You are an autonomous coding agent operating in a repository. "
        "You can inspect code, edit files, and run commands when needed."
    )


def build_direct_agent_prompt(
    request: str,
    *,
    project_name: str = "",
    project_description: str = "",
    project_stack: str = "",
    memory_block: str = "",
) -> tuple[str, str]:
    """Build the prompt for the lightweight direct TUI agent.

    Parameters
    ----------
    memory_block:
        Pre-formatted memory context block (from ``load_memory_for_injection``).
        Appended to the system prompt when non-empty.
    """
    system_parts = [
        _load_base_instruction(),
        "",
        "You are the default ColonyOS TUI agent handling a request directly.",
        "Do not enter the full PRD/tasks planning pipeline.",
        "If the request is a question, answer it directly and avoid edits.",
        "If the request is a small focused code change, make the change directly and run targeted verification.",
        "Keep scope tight. Do not broaden the task into a larger refactor unless the request explicitly requires it.",
        "If the task turns out to require substantial architecture or a multi-stage plan, say so clearly in your response instead of silently expanding scope.",
    ]

    if project_name:
        system_parts.append(f"\nProject: {project_name}")
    if project_description:
        system_parts.append(f"Description: {project_description}")
    if project_stack:
        system_parts.append(f"Stack: {project_stack}")

    if memory_block:
        system_parts.append(f"\n{memory_block}")

    safe_request = sanitize_untrusted_content(request)
    user_prompt = f"Handle this request directly inside the TUI:\n\n{safe_request}"
    return "\n".join(system_parts), user_prompt


def log_mode_selection(
    *,
    repo_root: Path,
    prompt: str,
    result: ModeAgentDecision,
    source: str = "tui",
) -> Path | None:
    """Log a TUI mode-selection decision to the audit trail."""
    runs_dir = repo_root / ".colonyos" / "runs"
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Failed to create runs directory: %s", runs_dir)
        return None

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    log_path = runs_dir / f"triage_{timestamp}.json"

    log_data = {
        "timestamp": now.isoformat(),
        "source": source,
        "prompt": sanitize_untrusted_content(prompt),
        "mode": result.mode.value,
        "confidence": result.confidence,
        "summary": result.summary,
        "reasoning": result.reasoning,
        "announcement": result.announcement,
    }

    try:
        log_path.write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Mode selection logged to %s", log_path)
        return log_path
    except OSError:
        logger.warning("Failed to write mode selection log: %s", log_path)
        return None


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
    complexity: str = "large"


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
        '"summary": str, "reasoning": str, "suggested_command": str|null, '
        '"complexity": str}',
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
        "Complexity:",
        '- "trivial" — tiny edits like copy fixes, renames, or single-file tweaks',
        '- "small" — limited implementation work that should skip planning',
        '- "large" — multi-file features, architecture changes, or unclear work',
        "",
        "Rules:",
        "- When uncertain between code_change and question, lean toward code_change "
        "(fail-open behavior).",
        "- confidence should reflect how certain you are about the classification.",
        "- summary should be a concise (1-2 sentence) description of what the user wants.",
        "- suggested_command is only required for status category.",
        '- complexity must always be one of "trivial", "small", or "large".',
    ]

    if project_name:
        system_parts.append(f"\nProject: {_sanitize_metadata(project_name)}")
    if project_description:
        system_parts.append(f"Description: {_sanitize_metadata(project_description)}")
    if project_stack:
        system_parts.append(f"Stack: {_sanitize_metadata(project_stack)}")
    if vision:
        system_parts.append(f"Vision: {_sanitize_metadata(vision)}")

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
    complexity = str(data.get("complexity", "large")).lower()
    if complexity not in {"trivial", "small", "large"}:
        complexity = "large"

    return RouterResult(
        category=category,
        confidence=confidence,
        summary=str(data.get("summary", "")),
        reasoning=str(data.get("reasoning", "")),
        suggested_command=data.get("suggested_command") or None,
        complexity=complexity,
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
    model: str | None = None,
) -> RouterResult:
    """Run the LLM-based intent router on a user query.

    Uses a single-turn low-budget classification call with no tool access.
    The model defaults to the configured router model and falls back to
    ``opus`` when no config is available.

    Args:
        query: The user's input query to classify.
        repo_root: Repository root directory. Falls back to cwd if not provided.
        project_name: Name of the project for context.
        project_description: Brief description of the project.
        project_stack: Technology stack of the project.
        vision: Project vision statement.
        source: Origin of the query (cli, repl, slack) for logging.
        model: Optional override for the router model.

    Returns:
        RouterResult with the classification.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.config import RouterConfig, load_config
    from colonyos.models import Phase

    cwd = repo_root if repo_root is not None else Path.cwd()
    resolved_model = model
    if resolved_model is None:
        if repo_root is not None:
            resolved_model = load_config(repo_root).router.model
        else:
            resolved_model = RouterConfig().model

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
        model=resolved_model,
        budget_usd=0.05,  # tiny budget for routing
        allowed_tools=[],  # no tool access
    )

    # Extract text from artifacts. run_phase_sync returns a single-entry dict
    # keyed by artifact name; we take the first (and only) value. If the SDK
    # ever returns multiple artifacts, revisit to use a well-known key.
    raw_text = extract_result_text(result.artifacts)
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

    # Extract answer from artifacts (single-entry dict; see route_query comment).
    answer = extract_result_text(result.artifacts)
    if answer:
        return answer

    if result.error:
        logger.warning("Q&A agent call failed: %s", result.error[:200])
        return f"I was unable to answer your question due to an error: {result.error[:200]}"

    return "I was unable to find an answer to your question."


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
        "complexity": result.complexity,
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
