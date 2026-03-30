"""Prompt routing, intent classification, and execution-mode dispatch.

Contains the ``RouteOutcome`` dataclass and helpers that decide *how* to
execute an incoming user prompt (direct agent, review-only, cleanup, full
plan-implement loop, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from colonyos.config import ColonyConfig, load_config
from colonyos.orchestrator import (
    extract_review_verdict,
    run_standalone_review,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteOutcome:
    """Structured result of mode selection before request execution."""

    mode: str = "plan_implement_loop"
    announcement: str | None = None
    display_text: str | None = None
    skip_planning: bool = False
    from_prd: str | None = None


def _route_prompt(
    prompt: str,
    config: ColonyConfig,
    repo_root: Path,
    source: str,
    quiet: bool = False,
    continuation_active: bool = False,
) -> RouteOutcome:
    """Choose a TUI/CLI execution mode for the incoming prompt."""
    from colonyos.router import (
        ModeAgentMode,
        choose_tui_mode,
        log_mode_selection,
    )

    if not quiet:
        click.echo(click.style("Choosing the best mode...", dim=True))

    decision = choose_tui_mode(
        prompt,
        repo_root=repo_root,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        vision=config.vision,
        source=source,
        continuation_active=continuation_active,
    )

    log_mode_selection(
        repo_root=repo_root,
        prompt=prompt,
        result=decision,
        source=source,
    )

    if decision.confidence < config.router.confidence_threshold:
        if continuation_active:
            return RouteOutcome(
                mode=ModeAgentMode.DIRECT_AGENT.value,
                announcement="Continuing conversation.",
            )
        if not quiet:
            click.echo(click.style(
                f"Low confidence ({decision.confidence:.0%}), entering feature planning mode...",
                dim=True,
            ))
        return RouteOutcome(
            mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP.value,
            announcement="Entering feature planning mode.",
        )

    if decision.mode == ModeAgentMode.DIRECT_AGENT:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.IMPLEMENT_ONLY:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.REVIEW_ONLY:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.CLEANUP_LOOP:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.FALLBACK:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
            display_text=(
                "I need a bit more direction before I choose a workflow. "
                "Try asking a concrete coding question or describing the change you want."
            ),
        )

    return RouteOutcome(
        mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP.value,
        announcement=decision.announcement,
        skip_planning=decision.skip_planning,
    )


def _handle_routed_query(
    prompt: str,
    config: ColonyConfig,
    repo_root: Path,
    source: str,
    quiet: bool = False,
) -> str | None:
    """Compatibility wrapper preserving the legacy category-based helper behavior."""
    from colonyos.router import (
        RouterCategory,
        answer_question,
        log_router_decision,
        route_query,
    )

    if not quiet:
        click.echo(click.style("Classifying intent...", dim=True))

    router_result = route_query(
        prompt,
        repo_root=repo_root,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        vision=config.vision,
        source=source,
    )
    log_router_decision(
        repo_root=repo_root,
        prompt=prompt,
        result=router_result,
        source=source,
    )

    if router_result.confidence < config.router.confidence_threshold:
        return None
    if router_result.category == RouterCategory.QUESTION:
        return answer_question(
            prompt,
            repo_root=repo_root,
            project_name=config.project.name if config.project else "",
            project_description=config.project.description if config.project else "",
            project_stack=config.project.stack if config.project else "",
            model=config.router.qa_model,
            qa_budget=config.router.qa_budget,
        )
    if router_result.category == RouterCategory.STATUS:
        return router_result.suggested_command or "colonyos status"
    if router_result.category == RouterCategory.OUT_OF_SCOPE:
        return (
            "This request doesn't seem related to coding or this project. "
            "For code changes, describe the feature you want to build."
        )
    return None


def _run_direct_agent(
    request: str,
    *,
    repo_root: Path,
    config: ColonyConfig,
    ui: Any | None,
    resume_session_id: str | None = None,
) -> tuple[bool, str | None]:
    """Handle a request directly with a lightweight general coding agent.

    Returns a ``(success, session_id)`` tuple.  The *session_id* can be
    passed back as *resume_session_id* on the next call to continue the
    conversation via the SDK's native session-resume mechanism.
    """
    import re

    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase
    from colonyos.router import build_direct_agent_prompt

    # Defense-in-depth: validate session ID format before passing to the SDK.
    # Session IDs should be alphanumeric with hyphens/underscores only.
    if resume_session_id is not None and not re.fullmatch(
        r"[A-Za-z0-9_-]+", resume_session_id
    ):
        resume_session_id = None
    # Inject memory context if enabled
    memory_block = ""
    if config.memory.enabled:
        try:
            from colonyos.memory import MemoryStore, load_memory_for_injection
            with MemoryStore(repo_root, max_entries=config.memory.max_entries) as mem_store:
                memory_block = load_memory_for_injection(
                    mem_store, "direct_agent", request,
                    max_tokens=config.memory.max_inject_tokens,
                )
        except Exception:
            logger.warning("Failed to load memory for injection, continuing without memory")

    system, user = build_direct_agent_prompt(
        request,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        memory_block=memory_block,
    )
    model = config.router.model or config.get_model(Phase.IMPLEMENT)
    budget = config.budget.per_phase

    if ui is not None:
        ui.phase_header("Direct", budget, model)

    result = run_phase_sync(
        Phase.QA,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=model,
        budget_usd=budget,
        ui=ui,
        resume=resume_session_id,
    )

    # Graceful fallback: if the run failed and we were resuming a session,
    # retry once without resume to start a fresh conversation.
    if not result.success and resume_session_id is not None:
        result = run_phase_sync(
            Phase.QA,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=model,
            budget_usd=budget,
            ui=ui,
            resume=None,
        )

    return (result.success, result.session_id or None)


def _run_review_only_flow(
    *,
    repo_root: Path,
    config: ColonyConfig,
    verbose: bool,
    quiet: bool,
) -> bool:
    """Review the current branch against main without entering the plan loop."""
    from colonyos.cli._helpers import _current_branch_name
    from colonyos.cli._display import _print_review_summary
    from colonyos.orchestrator import reviewer_personas

    branch = _current_branch_name(repo_root)
    base = "main"
    if branch == base:
        raise click.ClickException(
            "Review-only mode expects a feature branch. Switch branches or use `review <branch>`."
        )

    all_approved, phase_results, total_cost, decision_verdict = run_standalone_review(
        branch,
        base,
        repo_root,
        config,
        verbose=verbose,
        quiet=quiet,
        no_fix=True,
        decide=False,
    )
    _print_review_summary(phase_results, reviewer_personas(config), total_cost, decision_verdict=decision_verdict)
    return all_approved


def _run_cleanup_loop() -> None:
    """Run the default cleanup loop inside the current repository."""
    from colonyos.cli._helpers import _find_repo_root
    from colonyos.cli._legacy import _run_cleanup_scan_impl

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    _run_cleanup_scan_impl(
        repo_root,
        config,
        max_lines=None,
        max_functions=None,
        use_ai=True,
        refactor_file=None,
    )


# Sentinel value returned by _handle_tui_command when the user resets the conversation.
# Used to detect /new without fragile substring matching on user-facing text.
_NEW_CONVERSATION_SIGNAL = "Conversation cleared."
_AUTO_COMMAND_SIGNAL = "__AUTO_COMMAND__"
_SAFE_TUI_COMMANDS = {
    "auto",
    "doctor",
    "help",
    "new",
    "queue",
    "show",
    "stats",
    "status",
}


def _handle_tui_command(text: str, *, config: ColonyConfig) -> tuple[bool, str | None, bool]:
    """Handle REPL-style commands from the Textual TUI.

    Returns ``(handled, output, should_exit)``. When ``handled`` is False,
    the caller should treat the input as a normal feature prompt.
    """
    import shlex

    from colonyos.cli._repl import (
        _capture_click_output,
        _invoke_cli_command,
        _print_repl_help,
        _repl_top_level_names,
    )

    stripped = text.strip()
    if not stripped:
        return False, None, False

    lowered = stripped.lower()
    if lowered in {"quit", "exit"}:
        return True, "Exiting ColonyOS TUI.", True

    if lowered == "new":
        return True, _NEW_CONVERSATION_SIGNAL, False
    if lowered == "help":
        return True, _capture_click_output(_print_repl_help), False

    if lowered.startswith("help "):
        command_name = stripped.split(None, 1)[1].strip()
        return True, _capture_click_output(_print_repl_help, command_name), False

    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()

    if not tokens or tokens[0] not in _repl_top_level_names():
        return False, None, False

    command_name = tokens[0]
    if command_name in {"run", "tui"}:
        return (
            True,
            "Use the TUI directly: type a feature prompt instead of `run`, and "
            "you are already inside `tui`.",
            False,
        )
    if command_name in {"ui", "watch"}:
        return (
            True,
            f"`{command_name}` is not launched inside the TUI. Run "
            f"`colonyos {command_name}` from a normal shell.",
            False,
        )
    if command_name == "auto":
        if not (config.auto_approve or "--no-confirm" in tokens):
            return (
                True,
                "`auto` inside the TUI needs `--no-confirm` unless `auto_approve` is enabled.",
                False,
            )
        return True, _AUTO_COMMAND_SIGNAL, False
    if command_name not in _SAFE_TUI_COMMANDS:
        return (
            True,
            f"`{command_name}` is not supported inside the TUI. Run "
            f"`colonyos {command_name}` from a normal shell.",
            False,
        )

    output = _capture_click_output(_invoke_cli_command, tokens)
    if not output:
        output = f"`{' '.join(tokens)}` completed."
    return True, output, False
