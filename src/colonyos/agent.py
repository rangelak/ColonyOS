from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import StreamEvent, SystemMessage

from colonyos.models import Phase, PhaseResult

if TYPE_CHECKING:
    from colonyos.ui import NullUI, PhaseUI

logger = logging.getLogger(__name__)

_API_KEY_SOURCE_LABELS = {
    "none": "Claude subscription (no API key)",
    "environment": "ANTHROPIC_API_KEY env var",
    "config": "Claude config file",
}


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


def _friendly_error(exc: Exception) -> str:
    """Extract a human-readable message from SDK exceptions."""
    raw = str(exc)
    stderr = getattr(exc, "stderr", None) or ""
    result = getattr(exc, "result", None) or ""

    for text in (result, stderr, raw):
        lower = text.lower()
        if "credit balance" in lower:
            api_key_hint = ""
            if os.environ.get("ANTHROPIC_API_KEY"):
                api_key_hint = (
                    " (ANTHROPIC_API_KEY is set in your environment — "
                    "this may be overriding your Claude subscription. "
                    "Unset it or remove it from .env to use your subscription.)"
                )
            return f"Credit balance is too low.{api_key_hint}"
        if "authentication" in lower or "unauthorized" in lower:
            return f"Authentication failed — check your API key or Claude login. {text.strip()}"
        if "rate limit" in lower:
            return f"Rate limited by the API. {text.strip()}"

    if "exit code 1" in raw and not stderr:
        return (
            f"{raw} — the Claude CLI exited without details. "
            "Try running `claude -p 'hello'` to check if it works."
        )
    return f"{raw}\n{stderr}".strip()


async def run_phase(
    phase: Phase,
    prompt: str,
    *,
    cwd: Path,
    system_prompt: str,
    model: str | None = None,
    budget_usd: float = 5.0,
    max_turns: int | None = None,
    agents: dict[str, AgentDefinition] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: str = "bypassPermissions",
    ui: PhaseUI | NullUI | None = None,
) -> PhaseResult:
    """Run a single phase by invoking Claude Code with the given prompt and instructions."""
    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
        if agents:
            allowed_tools.append("Agent")

    options = ClaudeAgentOptions(
        cwd=cwd,
        system_prompt=system_prompt,
        model=model,
        max_turns=max_turns,
        max_budget_usd=budget_usd,
        permission_mode=permission_mode,
        allowed_tools=allowed_tools,
        agents=agents,
        include_partial_messages=ui is not None,
    )

    if ui is None:
        _log(f"Starting {phase.value} phase (budget=${budget_usd:.2f})...")

    result_msg: ResultMessage | None = None
    current_tool: str | None = None
    auth_shown = False

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and not auth_shown:
                source = message.data.get("apiKeySource")
                if source:
                    auth_shown = True
                    label = _API_KEY_SOURCE_LABELS.get(source, source)
                    if ui is not None:
                        ui.on_text_delta(f"  Auth: {label}\n")
                    else:
                        _log(f"Auth: {label}")

            elif isinstance(message, StreamEvent) and ui is not None:
                event = message.event
                etype = event.get("type")

                if etype == "content_block_start":
                    cb = event.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        current_tool = cb.get("name", "unknown")
                        ui.on_tool_start(current_tool)

                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        ui.on_text_delta(delta.get("text", ""))
                    elif dtype == "input_json_delta":
                        ui.on_tool_input_delta(delta.get("partial_json", ""))

                elif etype == "content_block_stop":
                    if current_tool:
                        ui.on_tool_done()
                        current_tool = None

            elif isinstance(message, AssistantMessage) and ui is not None:
                ui.on_turn_complete()

            elif isinstance(message, ResultMessage):
                result_msg = message

    except Exception as exc:
        friendly = _friendly_error(exc)
        error_msg = f"Phase {phase.value} failed: {friendly}"
        if ui is not None:
            ui.phase_error(error_msg)
        else:
            _log(error_msg)
        logger.debug("Phase %s raw exception: %r", phase.value, exc)
        return PhaseResult(
            phase=phase,
            success=False,
            model=model,
            error=friendly,
        )

    if result_msg is None:
        err = "No result message received from Claude Code"
        if ui is not None:
            ui.phase_error(err)
        else:
            _log(err)
        return PhaseResult(
            phase=phase,
            success=False,
            model=model,
            error=err,
        )

    success = not result_msg.is_error
    cost = result_msg.total_cost_usd or 0
    turns = result_msg.num_turns
    duration = result_msg.duration_ms

    if ui is not None:
        if success:
            ui.phase_complete(cost, turns, duration)
        else:
            ui.phase_error(result_msg.result or "Unknown error")
    else:
        _log(
            f"Phase {phase.value} {'completed' if success else 'failed'} "
            f"(cost=${cost:.4f}, turns={turns}, duration={duration}ms)"
        )

    return PhaseResult(
        phase=phase,
        success=success,
        cost_usd=result_msg.total_cost_usd,
        duration_ms=result_msg.duration_ms,
        session_id=result_msg.session_id,
        model=model,
        error=result_msg.result if result_msg.is_error else None,
        artifacts={"result": result_msg.result or ""},
    )


def run_phase_sync(
    phase: Phase,
    prompt: str,
    *,
    cwd: Path,
    system_prompt: str,
    model: str | None = None,
    budget_usd: float = 5.0,
    max_turns: int | None = None,
    agents: dict[str, AgentDefinition] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: str = "bypassPermissions",
    ui: PhaseUI | NullUI | None = None,
) -> PhaseResult:
    """Synchronous wrapper around run_phase for use in non-async contexts."""
    return asyncio.run(
        run_phase(
            phase,
            prompt,
            cwd=cwd,
            system_prompt=system_prompt,
            model=model,
            budget_usd=budget_usd,
            max_turns=max_turns,
            agents=agents,
            allowed_tools=allowed_tools,
            permission_mode=permission_mode,
            ui=ui,
        )
    )


async def run_phases_parallel(calls: list[dict]) -> list[PhaseResult]:
    """Run multiple phase calls concurrently via asyncio.gather."""
    tasks = [run_phase(**c) for c in calls]
    return list(await asyncio.gather(*tasks))


def run_phases_parallel_sync(calls: list[dict]) -> list[PhaseResult]:
    """Synchronous wrapper for run_phases_parallel."""
    return asyncio.run(run_phases_parallel(calls))
