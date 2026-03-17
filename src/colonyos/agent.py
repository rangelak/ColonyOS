from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from colonyos.models import Phase, PhaseResult


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
) -> PhaseResult:
    """Run a single phase by invoking Claude Code with the given prompt and instructions."""
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
    )

    _log(f"Starting {phase.value} phase (budget=${budget_usd:.2f})...")

    result_msg: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_msg = message
    except Exception as exc:
        _log(f"Phase {phase.value} failed: {type(exc).__name__}: {exc}")
        stderr = getattr(exc, "stderr", None) or ""
        if stderr:
            _log(f"stderr: {stderr}")
        return PhaseResult(
            phase=phase,
            success=False,
            error=f"{exc}\n{stderr}".strip(),
        )

    if result_msg is None:
        return PhaseResult(
            phase=phase,
            success=False,
            error="No result message received from Claude Code",
        )

    success = not result_msg.is_error
    _log(
        f"Phase {phase.value} {'completed' if success else 'failed'} "
        f"(cost=${result_msg.total_cost_usd or 0:.4f}, "
        f"turns={result_msg.num_turns}, "
        f"duration={result_msg.duration_ms}ms)"
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
        )
    )
