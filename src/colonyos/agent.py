from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ProcessError,
    ResultMessage,
    query,
)
from claude_code_sdk._errors import MessageParseError

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
) -> PhaseResult:
    """Run a single phase by invoking Claude Code with the given prompt and instructions."""
    options = ClaudeCodeOptions(
        cwd=cwd,
        system_prompt=system_prompt,
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
    )

    _log(f"Starting {phase.value} phase (budget=${budget_usd:.2f})...")

    result_msg: ResultMessage | None = None
    got_assistant_msg = False
    try:
        stream = query(prompt=prompt, options=options)
        while True:
            try:
                message = await stream.__anext__()
            except StopAsyncIteration:
                break
            except MessageParseError:
                continue
            if isinstance(message, ResultMessage):
                result_msg = message
            elif isinstance(message, AssistantMessage):
                got_assistant_msg = True
    except ProcessError as exc:
        stderr = getattr(exc, "stderr", None) or ""
        _log(f"Phase {phase.value} failed (exit={getattr(exc, 'exit_code', '?')})")
        if stderr:
            _log(f"stderr: {stderr}")
        else:
            _log(f"error: {exc}")
        return PhaseResult(
            phase=phase,
            success=False,
            error=f"{exc}\n{stderr}".strip(),
        )
    except Exception as exc:
        _log(f"Phase {phase.value} failed: {type(exc).__name__}: {exc}")
        return PhaseResult(
            phase=phase,
            success=False,
            error=str(exc),
        )

    if result_msg:
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

    if got_assistant_msg:
        _log(
            f"Phase {phase.value} completed (no ResultMessage due to SDK "
            f"compat issue, treating as success)"
        )
        return PhaseResult(phase=phase, success=True)

    return PhaseResult(
        phase=phase,
        success=False,
        error="No response received from Claude Code",
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
        )
    )
