"""Pipeline lifecycle hook execution engine.

Provides a standalone ``HookRunner`` class that executes user-defined shell
commands at pipeline phase boundaries.  Designed to be fully testable in
isolation — no orchestrator dependency required.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from colonyos.config import ColonyConfig, HookConfig
from colonyos.sanitize import sanitize_hook_output

logger = logging.getLogger(__name__)

# Environment variable name patterns that are stripped from the subprocess
# environment to prevent secret leakage.  A key is scrubbed if it matches
# one of the explicit names OR contains one of the substrings (case-insensitive).
_SCRUBBED_ENV_EXACT: frozenset[str] = frozenset({
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "SLACK_BOT_TOKEN",
})

_SCRUBBED_ENV_SUBSTRINGS: tuple[str, ...] = (
    "SECRET",
    "_TOKEN",
    "_KEY",
    "API_KEY",
    "PASSWORD",
    "CREDENTIAL",
)

# Substrings that look like secret-related names but are actually safe
# system variables that should NOT be scrubbed.
_SAFE_ENV_EXACT: frozenset[str] = frozenset({
    "TERM_SESSION_ID",
    "SSH_AUTH_SOCK",
    "KEYCHAIN_PATH",
    "TOKENIZERS_PARALLELISM",
    "GPG_AGENT_INFO",
})


def _should_scrub_key(key: str) -> bool:
    """Return True if the environment variable key should be removed."""
    if key in _SCRUBBED_ENV_EXACT:
        return True
    if key in _SAFE_ENV_EXACT:
        return False
    upper = key.upper()
    return any(sub in upper for sub in _SCRUBBED_ENV_SUBSTRINGS)


@dataclass(frozen=True)
class HookContext:
    """Contextual information passed to hook subprocesses as env vars."""

    run_id: str
    phase: str
    branch: str
    repo_root: Path
    status: str = "running"


@dataclass
class HookResult:
    """Outcome of a single hook execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    success: bool
    blocking: bool = True
    injected_output: str | None = None


def _build_hook_env(context: HookContext) -> dict[str, str]:
    """Build subprocess environment: inherit os.environ, strip secrets, add COLONYOS_* vars."""
    env: dict[str, str] = {
        k: v for k, v in os.environ.items() if not _should_scrub_key(k)
    }
    # Add COLONYOS_* context variables
    env["COLONYOS_RUN_ID"] = context.run_id
    env["COLONYOS_PHASE"] = context.phase
    env["COLONYOS_BRANCH"] = context.branch
    env["COLONYOS_REPO_ROOT"] = str(context.repo_root)
    env["COLONYOS_STATUS"] = context.status
    return env


class HookRunner:
    """Executes pipeline lifecycle hooks defined in ColonyConfig.

    Usage::

        runner = HookRunner(config)
        results = runner.run_hooks("pre_implement", context)
        for r in results:
            if not r.success and hook_was_blocking:
                # handle failure
    """

    def __init__(self, config: ColonyConfig) -> None:
        self._hooks = config.hooks
        self._in_failure_handler = False

    def get_hooks(self, event: str) -> list[HookConfig]:
        """Return the list of HookConfigs for a given event (public accessor)."""
        return self._hooks.get(event, [])

    def run_hooks(self, event: str, context: HookContext) -> list[HookResult]:
        """Execute all hooks for the given event in definition order.

        For blocking hooks, stops on the first failure.
        For non-blocking hooks, logs errors and continues.

        Returns:
            List of HookResult for each hook that was executed.
        """
        hook_configs = self._hooks.get(event, [])
        if not hook_configs:
            return []

        env = _build_hook_env(context)
        results: list[HookResult] = []

        for hook in hook_configs:
            result = self._execute_hook(hook, context, env)
            results.append(result)

            if not result.success and hook.blocking:
                logger.warning(
                    "Blocking hook failed for event=%s cmd=%s exit=%d",
                    event,
                    hook.command[:80],
                    result.exit_code,
                )
                break
            elif not result.success:
                logger.info(
                    "Non-blocking hook failed for event=%s cmd=%s exit=%d (continuing)",
                    event,
                    hook.command[:80],
                    result.exit_code,
                )

        return results

    def run_on_failure(self, context: HookContext) -> list[HookResult]:
        """Run on_failure hooks best-effort.

        Failures are logged but never raised.  A recursion guard prevents
        on_failure hooks from triggering further on_failure hooks.
        """
        if self._in_failure_handler:
            logger.debug("Skipping on_failure hooks — already in failure handler")
            return []

        self._in_failure_handler = True
        try:
            hook_configs = self._hooks.get("on_failure", [])
            if not hook_configs:
                return []

            env = _build_hook_env(context)
            results: list[HookResult] = []

            for hook in hook_configs:
                try:
                    result = self._execute_hook(hook, context, env)
                    results.append(result)
                    if not result.success:
                        logger.info(
                            "on_failure hook failed (swallowed): cmd=%s exit=%d",
                            hook.command[:80],
                            result.exit_code,
                        )
                except Exception:
                    logger.exception("on_failure hook raised unexpectedly: cmd=%s", hook.command[:80])
                    results.append(HookResult(
                        command=hook.command,
                        exit_code=-1,
                        stdout="",
                        stderr="unexpected exception",
                        duration_ms=0,
                        timed_out=False,
                        success=False,
                    ))

            return results
        finally:
            self._in_failure_handler = False

    def _execute_hook(
        self,
        hook: HookConfig,
        context: HookContext,
        env: dict[str, str],
    ) -> HookResult:
        """Execute a single hook command as a subprocess."""
        cmd_preview = hook.command[:80]
        start = time.monotonic()
        timed_out = False
        exit_code = -1
        stdout = ""
        stderr = ""

        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
                cwd=str(context.repo_root),
                timeout=hook.timeout_seconds,
                env=env,
            )
            exit_code = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            logger.warning("Hook timed out after %ds: %s", hook.timeout_seconds, cmd_preview)
        except Exception:
            logger.exception("Hook execution error: %s", cmd_preview)
            exit_code = -1

        duration_ms = int((time.monotonic() - start) * 1000)
        success = exit_code == 0 and not timed_out

        # Handle inject_output
        injected_output: str | None = None
        if hook.inject_output and success:
            injected_output = sanitize_hook_output(stdout)

        logger.info(
            "Hook %s cmd=%s exit=%d duration=%dms timed_out=%s",
            "OK" if success else "FAIL",
            cmd_preview,
            exit_code,
            duration_ms,
            timed_out,
        )

        return HookResult(
            command=hook.command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            success=success,
            blocking=hook.blocking,
            injected_output=injected_output,
        )
