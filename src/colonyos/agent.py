from __future__ import annotations

import asyncio
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
from claude_agent_sdk.types import StreamEvent

from colonyos.models import Phase, PhaseResult

if TYPE_CHECKING:
    from colonyos.ui import NullUI, PhaseUI


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


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
        permission_mode="bypassPermissions",
        allowed_tools=allowed_tools,
        agents=agents,
        include_partial_messages=ui is not None,
    )

    if ui is None:
        _log(f"Starting {phase.value} phase (budget=${budget_usd:.2f})...")

    result_msg: ResultMessage | None = None
    current_tool: str | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, StreamEvent) and ui is not None:
                event = message.event
                etype = event.get("type")

                if etype == "content_block_start":
                    cb = event.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        current_tool = cb.get("name")
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
        error_msg = f"Phase {phase.value} failed: {type(exc).__name__}: {exc}"
        stderr = getattr(exc, "stderr", None) or ""
        if ui is not None:
            ui.phase_error(error_msg)
        else:
            _log(error_msg)
            if stderr:
                _log(f"stderr: {stderr}")
        return PhaseResult(
            phase=phase,
            success=False,
            error=f"{exc}\n{stderr}".strip(),
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
