from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import StreamEvent, SystemMessage

from colonyos.config import RetryConfig, _SAFETY_CRITICAL_PHASES
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


def _is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception represents a transient API error worth retrying.

    Checks structured attributes first (status_code), then falls back to string
    matching on the exception message, stderr, and result fields.

    Note: This is a workaround until the SDK provides structured error types.
    """
    # 1. Structured attribute check — most reliable when available
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return status_code in (429, 503, 529)

    # 2. String matching fallback — check all available text fields
    raw = str(exc)
    stderr = getattr(exc, "stderr", None) or ""
    result = getattr(exc, "result", None) or ""

    _TRANSIENT_PATTERNS = ("overloaded", "529", "503")
    for text in (raw, stderr, result):
        lower = text.lower()
        if any(pattern in lower for pattern in _TRANSIENT_PATTERNS):
            return True

    return False


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
        if "overloaded" in lower or "529" in lower:
            return "API is temporarily overloaded (529). Will retry..."

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
    resume: str | None = None,
    retry_config: RetryConfig | None = None,
) -> PhaseResult:
    """Run a single phase by invoking Claude Code with the given prompt and instructions.

    Wraps the query call in a retry loop for transient errors (429/503/529) with
    exponential backoff and full jitter. Permanent errors fail immediately.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
        if agents:
            allowed_tools.append("Agent")

    max_attempts = retry_config.max_attempts
    transient_errors = 0
    total_retry_delay = 0.0
    last_exc: Exception | None = None
    fallback_model_used: str | None = None

    # Build the list of (model, max_attempts) passes to try.
    # Pass 1: primary model. Pass 2 (optional): fallback model.
    passes: list[tuple[str | None, int]] = [(model, max_attempts)]
    if (
        retry_config.fallback_model is not None
        and phase.value not in _SAFETY_CRITICAL_PHASES
    ):
        passes.append((retry_config.fallback_model, max_attempts))

    overall_attempt = 0

    for pass_idx, (current_model, pass_max) in enumerate(passes):
        for attempt in range(1, pass_max + 1):
            overall_attempt += 1
            options = ClaudeAgentOptions(
                cwd=cwd,
                system_prompt=system_prompt,
                model=current_model,
                max_turns=max_turns,
                max_budget_usd=budget_usd,
                permission_mode=permission_mode,
                allowed_tools=allowed_tools,
                agents=agents,
                include_partial_messages=ui is not None,
                **({"resume": resume, "continue_conversation": True} if resume else {}),
            )

            if overall_attempt == 1 and ui is None:
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
                last_exc = exc

                if not _is_transient_error(exc) or attempt == pass_max:
                    # Permanent error or last attempt in this pass
                    transient_errors += 1 if _is_transient_error(exc) else 0

                    if _is_transient_error(exc) and pass_idx < len(passes) - 1:
                        # Transient + more passes available → switch to fallback
                        fallback_model_used = passes[pass_idx + 1][0]
                        fallback_msg = (
                            f"Retries exhausted on {current_model or 'default'}, "
                            f"falling back to {fallback_model_used}..."
                        )
                        if ui is not None:
                            ui.on_text_delta(f"\n🔄 {fallback_msg}\n")
                        else:
                            _log(fallback_msg)
                        break  # break inner loop to advance to next pass

                    # No more passes — return failure
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
                        model=current_model,
                        error=friendly,
                        retry_info={
                            "attempts": overall_attempt,
                            "transient_errors": transient_errors,
                            "fallback_model_used": fallback_model_used,
                            "total_retry_delay_seconds": total_retry_delay,
                        },
                    )

                # Transient error with remaining attempts — retry with backoff
                transient_errors += 1
                computed_delay = min(
                    retry_config.base_delay_seconds * (2 ** (attempt - 1)),
                    retry_config.max_delay_seconds,
                )
                delay = random.uniform(0, computed_delay)
                total_retry_delay += delay

                retry_msg = (
                    f"API overloaded, retrying in {delay:.0f}s "
                    f"(attempt {attempt}/{pass_max})..."
                )
                if ui is not None:
                    ui.on_text_delta(f"\n⏳ {retry_msg}\n")
                else:
                    _log(retry_msg)

                await asyncio.sleep(delay)
                continue

            # No exception — check result
            retry_info = {
                "attempts": overall_attempt,
                "transient_errors": transient_errors,
                "fallback_model_used": fallback_model_used,
                "total_retry_delay_seconds": total_retry_delay,
            }

            if result_msg is None:
                err = "No result message received from Claude Code"
                if ui is not None:
                    ui.phase_error(err)
                else:
                    _log(err)
                return PhaseResult(
                    phase=phase,
                    success=False,
                    model=current_model,
                    error=err,
                    retry_info=retry_info,
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
                model=current_model,
                error=result_msg.result if result_msg.is_error else None,
                artifacts={"result": result_msg.result or ""},
                retry_info=retry_info,
            )
        else:
            # Inner for-loop completed without break — no more attempts in this pass
            # This only happens if pass_max is 0 (defensive); continue to next pass
            continue
        # Inner loop was broken out of (fallback transition) — continue outer loop
        continue

    # Should not reach here, but handle defensively
    friendly = _friendly_error(last_exc) if last_exc else "Unknown error after retries"
    return PhaseResult(
        phase=phase,
        success=False,
        model=model,
        error=friendly,
        retry_info={
            "attempts": overall_attempt,
            "transient_errors": transient_errors,
            "fallback_model_used": fallback_model_used,
            "total_retry_delay_seconds": total_retry_delay,
        },
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
    resume: str | None = None,
    retry_config: RetryConfig | None = None,
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
            resume=resume,
            retry_config=retry_config,
        )
    )


async def run_phases_parallel(
    calls: list[dict],
    on_complete: Callable[[int, PhaseResult], None] | None = None,
) -> list[PhaseResult]:
    """Run multiple phase calls concurrently, invoking callback as each completes.

    Args:
        calls: List of kwargs dicts to pass to run_phase().
        on_complete: Optional callback invoked for each completed task.
            Signature: (index, result) where index is the original call order index.

    Returns:
        Results in the same order as the input calls list.
    """
    if not calls:
        return []

    # Create tasks with their original indices
    tasks_with_indices: list[tuple[int, asyncio.Task[PhaseResult]]] = []
    for i, call_kwargs in enumerate(calls):
        task = asyncio.create_task(run_phase(**call_kwargs))
        tasks_with_indices.append((i, task))

    # Map task to index for lookup
    task_to_index = {task: idx for idx, task in tasks_with_indices}

    # Collect results in completion order, storing by original index
    results: dict[int, PhaseResult] = {}
    pending = {task for _, task in tasks_with_indices}

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            idx = task_to_index[task]
            result = task.result()
            results[idx] = result
            if on_complete is not None:
                try:
                    on_complete(idx, result)
                except Exception:
                    logger.exception("Progress callback failed for index %d", idx)

    # Return results in original call order
    return [results[i] for i in range(len(calls))]


def run_phases_parallel_sync(
    calls: list[dict],
    on_complete: Callable[[int, PhaseResult], None] | None = None,
) -> list[PhaseResult]:
    """Synchronous wrapper for run_phases_parallel.

    Args:
        calls: List of kwargs dicts to pass to run_phase().
        on_complete: Optional callback invoked for each completed task.

    Returns:
        Results in the same order as the input calls list.
    """
    return asyncio.run(run_phases_parallel(calls, on_complete=on_complete))
