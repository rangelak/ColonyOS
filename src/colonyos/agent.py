from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import sys
import threading
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar, cast

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import StreamEvent, SystemMessage

from colonyos.cancellation import cancellation_scope, request_cancel
from colonyos.config import RetryConfig, _SAFETY_CRITICAL_PHASES
from colonyos.models import Phase, PhaseResult, RetryInfo

if TYPE_CHECKING:
    from colonyos.ui import NullUI, PhaseUI

logger = logging.getLogger(__name__)

_ACTIVE_PHASE_CONTROLLERS_LOCK = threading.Lock()
_ACTIVE_PHASE_CONTROLLERS: set["_SyncRunController"] = set()
_T = TypeVar("_T")

_API_KEY_SOURCE_LABELS = {
    "none": "Claude subscription (no API key)",
    "environment": "ANTHROPIC_API_KEY env var",
    "config": "Claude config file",
}

# Patterns for string-matching transient errors when no structured status_code
# is available. Uses word-boundary-aware regexes to avoid false positives on
# substrings like port numbers or file paths containing "503"/"529".
_TRANSIENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"overloaded", re.IGNORECASE),
    re.compile(r"\b529\b"),
    re.compile(r"\b503\b"),
)


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


def _is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception represents a transient API error worth retrying.

    Checks structured attributes first (status_code), then falls back to
    word-boundary-aware regex matching on the exception message, stderr, and
    result fields.

    Note: This is a workaround until the SDK provides structured error types.
    """
    # 1. Structured attribute check — most reliable when available
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return status_code in (429, 503, 529)

    # 2. Regex fallback — check all available text fields with word boundaries
    raw = str(exc)
    stderr = getattr(exc, "stderr", None) or ""
    result = getattr(exc, "result", None) or ""

    for text in (raw, stderr, result):
        if any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS):
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
        if any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS):
            return "API is temporarily overloaded. Will retry..."

    if "exit code 1" in raw and not stderr:
        return (
            f"{raw} — the Claude CLI exited without details. "
            "Try running `claude -p 'hello'` to check if it works."
        )
    return f"{raw}\n{stderr}".strip()


@dataclass
class _AttemptResult:
    """Result of a single query attempt inside the retry loop."""

    result_msg: ResultMessage | None = None
    error: Exception | None = None


@dataclass(eq=False)
class _SyncRunController:
    """Thread-safe cancellation bridge for sync wrappers around async runs."""

    label: str
    _loop: asyncio.AbstractEventLoop | None = None
    _task: asyncio.Task[PhaseResult | list[PhaseResult]] | None = None
    _cancel_requested: bool = False
    _cancel_reason: str = "Cancelled by user"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def attach(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[PhaseResult | list[PhaseResult]],
    ) -> None:
        with self._lock:
            self._loop = loop
            self._task = task
            cancel_requested = self._cancel_requested
            cancel_reason = self._cancel_reason
        if cancel_requested:
            self.cancel(cancel_reason)

    def cancel(self, reason: str = "Cancelled by user") -> None:
        with self._lock:
            self._cancel_requested = True
            self._cancel_reason = reason
            loop = self._loop
            task = self._task
        if loop is None or task is None or task.done():
            return
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            logger.debug(
                "Cancellation for %s arrived after the event loop closed",
                self.label,
                exc_info=True,
            )

    def detach(self) -> None:
        with self._lock:
            self._loop = None
            self._task = None

    @property
    def cancel_reason(self) -> str:
        with self._lock:
            return self._cancel_reason


def request_active_phase_cancel(reason: str = "Cancelled by user") -> int:
    """Request cancellation of all in-flight sync phase runs.

    Returns the number of active runs that were signaled.
    """
    with _ACTIVE_PHASE_CONTROLLERS_LOCK:
        controllers = list(_ACTIVE_PHASE_CONTROLLERS)
    for controller in controllers:
        controller.cancel(reason)
    return len(controllers)


def _register_active_phase_controller(controller: _SyncRunController) -> None:
    with _ACTIVE_PHASE_CONTROLLERS_LOCK:
        _ACTIVE_PHASE_CONTROLLERS.add(controller)


def _unregister_active_phase_controller(controller: _SyncRunController) -> None:
    with _ACTIVE_PHASE_CONTROLLERS_LOCK:
        _ACTIVE_PHASE_CONTROLLERS.discard(controller)


async def _run_phase_attempt(
    *,
    phase: Phase,
    prompt: str,
    options: ClaudeAgentOptions,
    ui: PhaseUI | NullUI | None,
    is_first_attempt: bool,
    budget_usd: float,
) -> _AttemptResult:
    """Execute a single query attempt, streaming messages to the UI.

    Returns an _AttemptResult containing either a ResultMessage or an exception.
    """
    if is_first_attempt and ui is None:
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
                        tool_name = cb.get("name")
                        current_tool = tool_name if isinstance(tool_name, str) and tool_name else "unknown"
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
        return _AttemptResult(error=exc)

    return _AttemptResult(result_msg=result_msg)


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

    When a ``fallback_model`` is configured, the primary model gets ``max_attempts``
    tries and the fallback model gets its own ``max_attempts`` tries, so the total
    number of attempts can be up to ``2 * max_attempts``. Fallback is disabled for
    safety-critical phases (review, decision, fix).
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
    # Total attempts can be up to 2 * max_attempts when fallback is configured.
    passes: list[tuple[str | None, int]] = [(model, max_attempts)]
    if (
        retry_config.fallback_model is not None
        and phase.value not in _SAFETY_CRITICAL_PHASES
    ):
        passes.append((retry_config.fallback_model, max_attempts))

    overall_attempt = 0
    # resume is only valid for the first attempt — after a transient error kills
    # the query, the session is dead and retries must restart from scratch.
    current_resume = resume

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
                **({"resume": current_resume, "continue_conversation": True} if current_resume else {}),
            )

            attempt_result = await _run_phase_attempt(
                phase=phase,
                prompt=prompt,
                options=options,
                ui=ui,
                is_first_attempt=(overall_attempt == 1),
                budget_usd=budget_usd,
            )

            if attempt_result.error is not None:
                exc = attempt_result.error
                last_exc = exc
                is_transient = _is_transient_error(exc)

                if not is_transient or attempt == pass_max:
                    # Permanent error or last attempt in this pass
                    transient_errors += 1 if is_transient else 0

                    if is_transient and pass_idx < len(passes) - 1:
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
                        retry_info=RetryInfo(
                            attempts=overall_attempt,
                            transient_errors=transient_errors,
                            fallback_model_used=fallback_model_used,
                            total_retry_delay_seconds=total_retry_delay,
                        ),
                    )

                # Transient error with remaining attempts — retry with backoff
                transient_errors += 1
                current_resume = None  # Session is dead after transient error
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
            result_msg = attempt_result.result_msg
            retry_info = RetryInfo(
                attempts=overall_attempt,
                transient_errors=transient_errors,
                fallback_model_used=fallback_model_used,
                total_retry_delay_seconds=total_retry_delay,
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
        # Inner loop either completed (all attempts used) or broke out
        # (fallback transition). Either way, continue to the next pass.

    # Should not reach here, but handle defensively
    friendly = _friendly_error(last_exc) if last_exc else "Unknown error after retries"
    return PhaseResult(
        phase=phase,
        success=False,
        model=current_model,
        error=friendly,
        retry_info=RetryInfo(
            attempts=overall_attempt,
            transient_errors=transient_errors,
            fallback_model_used=fallback_model_used,
            total_retry_delay_seconds=total_retry_delay,
        ),
    )


def _run_async_sync(
    coro_factory: Callable[[], Awaitable[_T]],
    *,
    label: str,
) -> _T:
    """Run an async coroutine in a worker thread that supports cancellation."""
    controller = _SyncRunController(label=label)
    done = threading.Event()
    outcome: dict[str, object] = {}

    def _worker() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(coro_factory())  # type: ignore[arg-type]
        controller.attach(loop, task)
        try:
            outcome["result"] = loop.run_until_complete(task)
        except asyncio.CancelledError:
            outcome["cancelled"] = controller.cancel_reason
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            try:
                pending = [item for item in asyncio.all_tasks(loop) if not item.done()]
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                controller.detach()
                loop.close()
                done.set()

    worker = threading.Thread(target=_worker, name=f"agent-{label}", daemon=True)
    _register_active_phase_controller(controller)
    try:
        with cancellation_scope(controller.cancel):
            worker.start()
            try:
                while not done.wait(0.1):
                    pass
            except KeyboardInterrupt:
                controller.cancel("Interrupted by user (Ctrl+C)")
                worker.join(timeout=10)
                raise
    finally:
        _unregister_active_phase_controller(controller)

    worker.join(timeout=0.1)
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    if "cancelled" in outcome:
        raise KeyboardInterrupt(str(outcome["cancelled"]))
    return cast(_T, outcome["result"])


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
    return _run_async_sync(
        lambda: run_phase(
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
        ),
        label=f"phase-{phase.value}",
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

    try:
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
    except asyncio.CancelledError:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise

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
    return _run_async_sync(
        lambda: run_phases_parallel(calls, on_complete=on_complete),
        label="parallel-phases",
    )
