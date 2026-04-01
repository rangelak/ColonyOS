"""ColonyOS Daemon — fully autonomous 24/7 engineering agent.

Unifies Slack listening, GitHub Issue polling, CEO idle-fill scheduling,
cleanup scheduling, and priority queue execution into a single supervised
long-running process.  Designed for systemd deployment on a VM.

Architecture:
    Single process, multiple threads.  One pipeline runs at a time
    (sequential execution).  Shared state protected by ``threading.Lock``.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from colonyos.agent import request_active_phase_cancel
from colonyos.cancellation import cancellation_scope, request_cancel
from colonyos.config import ColonyConfig, load_config
from colonyos.daemon_state import (
    DaemonState,
    atomic_write_json,
    load_daemon_state,
    save_daemon_state,
)
from colonyos.models import (
    PreflightError,
    QueueItem,
    QueueItemStatus,
    QueueState,
    QueueStatus,
    RunLog,
    RunStatus,
    compute_priority,
)
from colonyos.queue_runtime import (
    archive_terminal_queue_items,
    attach_demand_signal,
    find_related_history_items,
    find_similar_queue_item,
    notification_targets,
    pending_queue_snapshot,
    reprioritize_queue,
    reprioritize_queue_item,
    select_next_pending_item,
)
from colonyos.runtime_lock import RepoRuntimeGuard, RuntimeBusyError
from colonyos.tui.monitor_protocol import encode_monitor_event

logger = logging.getLogger(__name__)

# Sentinel file used as a single-instance lock
_PID_FILE = ".colonyos/daemon.pid"

# How often the main loop checks for work (seconds)
_MAIN_LOOP_INTERVAL = 5
_DAEMON_WATCH_ID = "daemon"


class DaemonError(RuntimeError):
    """Raised for unrecoverable daemon errors."""


class _CombinedUI:
    """Forward phase UI events to a terminal UI and a secondary mirror UI."""

    _SECONDARY_CALL_TIMEOUT_SECONDS = 3.0

    def __init__(self, primary: Any, secondary: Any) -> None:
        self._primary = primary
        self._secondary = secondary

    def _secondary_call(self, method: str, *args: object, **kwargs: object) -> None:
        done = threading.Event()

        def _invoke() -> None:
            try:
                getattr(self._secondary, method)(*args, **kwargs)
            except Exception:
                logger.debug("Secondary UI call %s failed", method, exc_info=True)
            finally:
                done.set()

        thread = threading.Thread(
            target=_invoke,
            name=f"secondary-ui-{method}",
            daemon=True,
        )
        thread.start()
        if not done.wait(self._SECONDARY_CALL_TIMEOUT_SECONDS):
            logger.warning(
                "Secondary UI call %s timed out after %.1fs; continuing without waiting",
                method,
                self._SECONDARY_CALL_TIMEOUT_SECONDS,
            )

    def phase_header(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_header(*args, **kwargs)
        self._secondary_call("phase_header", *args, **kwargs)

    def phase_complete(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_complete(*args, **kwargs)
        self._secondary_call("phase_complete", *args, **kwargs)

    def phase_error(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_error(*args, **kwargs)
        self._secondary_call("phase_error", *args, **kwargs)

    def phase_note(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_note(*args, **kwargs)
        self._secondary_call("phase_note", *args, **kwargs)

    def slack_note(self, text: str) -> None:
        self._secondary_call("phase_note", text)

    def on_tool_start(self, *args: object) -> None:
        self._primary.on_tool_start(*args)
        self._secondary_call("on_tool_start", *args)

    def on_tool_input_delta(self, *args: object) -> None:
        self._primary.on_tool_input_delta(*args)
        self._secondary_call("on_tool_input_delta", *args)

    def on_tool_done(self) -> None:
        self._primary.on_tool_done()
        self._secondary_call("on_tool_done")

    def on_text_delta(self, *args: object) -> None:
        self._primary.on_text_delta(*args)
        self._secondary_call("on_text_delta", *args)

    def on_turn_complete(self) -> None:
        self._primary.on_turn_complete()
        self._secondary_call("on_turn_complete")


class _DaemonMonitorEventUI:
    """Emit structured TUI events over stdout for the daemon monitor."""

    def __init__(
        self,
        prefix: str = "",
        *,
        badge_text: str = "",
        badge_style: str = "",
    ) -> None:
        self._prefix = prefix
        self._badge_text = badge_text
        self._badge_style = badge_style
        self._tool_name: str | None = None
        self._tool_json = ""
        self._tool_displayed = False
        self._text_buf = ""
        self._in_tool = False
        self._turn_count = 0

    def _emit(self, payload: dict[str, Any]) -> None:
        sys.stdout.write(encode_monitor_event(payload) + "\n")
        sys.stdout.flush()

    def phase_header(
        self,
        phase_name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        self._turn_count = 0
        self._emit({
            "type": "phase_header",
            "phase_name": phase_name,
            "budget": budget,
            "model": model,
            "extra": extra,
        })

    def phase_complete(self, cost: float, turns: int, duration_ms: int) -> None:
        self._flush_text()
        self._emit({
            "type": "phase_complete",
            "cost": cost,
            "turns": turns,
            "duration_ms": duration_ms,
        })

    def phase_error(self, error: str) -> None:
        self._flush_text()
        self._emit({"type": "phase_error", "error": error})

    def phase_note(self, text: str) -> None:
        note = text.strip()
        if not note:
            return
        self._emit({"type": "notice", "text": note})

    def slack_note(self, text: str) -> None:
        """No-op: monitor event UIs are terminal-side only."""

    def on_tool_start(self, tool_name: str) -> None:
        self._flush_text()
        self._in_tool = True
        self._tool_name = tool_name
        self._tool_json = ""
        self._tool_displayed = False

    def on_tool_input_delta(self, partial_json: str) -> None:
        self._tool_json += partial_json
        if not self._tool_displayed:
            arg = self._try_extract_arg()
            if arg is not None:
                self._emit_tool_line(arg)
                self._tool_displayed = True

    def on_tool_done(self) -> None:
        if self._tool_name and not self._tool_displayed:
            arg = self._try_extract_arg() or ""
            self._emit_tool_line(arg)
        self._tool_name = None
        self._tool_json = ""
        self._tool_displayed = False
        self._in_tool = False

    def on_text_delta(self, text: str) -> None:
        if self._in_tool:
            return
        self._text_buf += text

    def on_turn_complete(self) -> None:
        self._flush_text()
        self._turn_count += 1
        self._emit({"type": "turn_complete", "turn_number": self._turn_count})

    def _flush_text(self) -> None:
        raw = self._text_buf.strip()
        self._text_buf = ""
        if not raw:
            return
        self._emit({
            "type": "text_block",
            "text": raw,
            "badge_text": self._badge_text,
            "badge_style": self._badge_style,
        })

    def _emit_tool_line(self, arg: str) -> None:
        from colonyos.ui import DEFAULT_TOOL_STYLE, TOOL_ARG_KEYS, TOOL_STYLE, _first_meaningful_line, _truncate

        name = self._tool_name or "?"
        style = TOOL_STYLE.get(name, DEFAULT_TOOL_STYLE)
        display_arg = arg
        if name in {"Agent", "Dispatch", "Task"} and display_arg:
            display_arg = _first_meaningful_line(display_arg)
        display_arg = _truncate(display_arg, 80) if display_arg else ""
        self._emit({
            "type": "tool_line",
            "tool_name": name,
            "arg": display_arg,
            "style": style,
            "badge_text": self._badge_text,
            "badge_style": self._badge_style,
        })

    def _try_extract_arg(self) -> str | None:
        from colonyos.ui import TOOL_ARG_KEYS

        if not self._tool_name:
            return None
        keys = TOOL_ARG_KEYS.get(self._tool_name)
        if not keys:
            return None
        try:
            data = json.loads(self._tool_json)
        except (json.JSONDecodeError, TypeError):
            return None
        for key in keys:
            value = data.get(key)
            if value:
                return str(value)
        return None


class Daemon:
    """Core daemon orchestrator.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    config:
        Pre-loaded ColonyConfig (if None, loaded from repo_root).
    max_budget:
        CLI override for daily budget cap (overrides config).
    max_hours:
        Maximum wall-clock hours before daemon exits.
    dry_run:
        If True, do not execute pipelines — just log what would run.
    verbose:
        Enable verbose logging.
    """

    def __init__(
        self,
        repo_root: Path,
        config: ColonyConfig | None = None,
        *,
        max_budget: float | None = None,
        unlimited_budget: bool = False,
        max_hours: float | None = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.config = config or load_config(repo_root)
        self.daemon_config = self.config.daemon
        self.dry_run = dry_run
        self.verbose = verbose
        self._monitor_mode = os.environ.get("COLONYOS_DAEMON_MONITOR") == "1"
        self._agent_lock = threading.Lock()

        # CLI overrides
        self.daily_budget = (
            None
            if unlimited_budget
            else max_budget if max_budget is not None else self.daemon_config.daily_budget_usd
        )
        self.max_hours = max_hours

        # Shared mutable state — protected by _lock
        self._lock = threading.Lock()
        self._notification_thread_locks: dict[str, threading.Lock] = {}
        self._notification_thread_locks_guard = threading.Lock()
        self._state = load_daemon_state(repo_root)
        self._queue_state = self._load_or_create_queue()
        self._pipeline_running = False
        self._pipeline_started_at: float | None = None
        self._pipeline_stalled: bool = False
        self._current_running_item: QueueItem | None = None
        self._watchdog_thread: threading.Thread | None = None

        # Shutdown coordination
        self._stop_event = threading.Event()
        self._started_at = time.monotonic()

        # Track last schedule times
        self._last_ceo_time: float = 0.0
        self._last_cleanup_time: float = 0.0
        self._last_heartbeat_time: float = 0.0
        self._last_github_poll_time: float = 0.0
        self._last_reprioritize_time: float = 0.0

        # Repo runtime guard
        self._runtime_guard: RepoRuntimeGuard | None = None

        # Outcome polling timestamp
        self._last_outcome_poll_time: float = 0.0
        self._last_pr_sync_time: float = 0.0
        self._last_digest_date: str | None = None

        # Budget alert flags (reset on daily budget reset)
        self._budget_80_alerted: bool = False
        self._budget_100_alerted: bool = False
        self._last_budget_incident_date: str | None = None

        self._slack_watch_state: Any | None = None
        self._slack_client: Any | None = None
        self._slack_client_ready = threading.Event()

        # Systemic failure tracking — recent error codes for pattern detection
        self._recent_failure_codes: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the daemon — main entry point.

        Acquires PID lock, performs crash recovery, installs signal
        handlers, starts background threads, and enters the main
        scheduling loop.  Blocks until ``stop()`` is called or a
        signal is received.
        """
        self._acquire_pid_lock()
        with cancellation_scope(lambda _reason: self.stop()):
            try:
                self._recover_from_crash()
                self._install_signal_handlers()
                self._state.daemon_started_at = datetime.now(timezone.utc).isoformat()
                self._persist_state()

                logger.info(
                    "ColonyOS daemon started (budget=%s, dry_run=%s)",
                    self._budget_cap_label(),
                    self.dry_run,
                )

                # Start embedded dashboard server
                self._start_dashboard_server()

                logger.info(
                    "Watchdog enabled: stall threshold=%ds",
                    self.daemon_config.watchdog_stall_seconds,
                )

                # Start background threads
                threads = self._start_threads()

                # Main scheduling loop
                try:
                    self._main_loop()
                except KeyboardInterrupt:
                    logger.warning("Daemon interrupted, shutting down immediately")

                # Wait for threads to finish
                self._stop_event.set()
                for t in threads:
                    t.join(timeout=10)

            finally:
                self._release_pid_lock()
                logger.info("ColonyOS daemon stopped")

    def stop(self) -> None:
        """Request graceful shutdown."""
        logger.info("Daemon shutdown requested")
        self._stop_event.set()

    def pause(self) -> None:
        """Pause the daemon — stop picking up new queue items."""
        with self._lock:
            self._state.paused = True
            self._persist_state()
        logger.info("Daemon paused via API")

    def resume(self) -> None:
        """Resume the daemon — start picking up queue items again."""
        with self._lock:
            self._state.paused = False
            self._persist_state()
        logger.info("Daemon resumed via API")

    def _start_dashboard_server(self) -> None:
        """Start the embedded web dashboard on a daemon thread.

        Uses uvicorn to serve the FastAPI app. The dashboard provides
        live daemon health via ``app.state.daemon_instance``. Errors
        during server startup or runtime are logged but never crash
        the daemon.
        """
        if not self.daemon_config.dashboard_enabled:
            logger.info("Dashboard disabled in config, skipping")
            return

        try:
            import uvicorn
            from colonyos.server import create_app
        except ImportError:
            logger.info(
                "Dashboard dependencies not installed (pip install colonyos[ui]), skipping"
            )
            return

        port = self.daemon_config.dashboard_port

        write_enabled = self.daemon_config.dashboard_write_enabled

        def _serve() -> None:
            try:
                app, auth_token = create_app(
                    self.repo_root, write_enabled=write_enabled
                )
                app.state.daemon_instance = self
                masked = auth_token[-4:] if len(auth_token) >= 4 else "****"
                logger.info(
                    "Dashboard started on http://127.0.0.1:%d (write=%s, token: ...%s)",
                    port,
                    write_enabled,
                    masked,
                )
                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_level="warning",
                )
                server = uvicorn.Server(config)
                server.run()
            except Exception:
                logger.warning("Dashboard server failed", exc_info=True)

        thread = threading.Thread(target=_serve, daemon=True, name="dashboard-server")
        thread.start()

    def _check_time_exceeded(self) -> bool:
        if not self.max_hours:
            return False
        elapsed = (time.monotonic() - self._started_at) / 3600
        return elapsed >= self.max_hours

    def _check_budget_exceeded(self) -> bool:
        allowed, _remaining = self._state.check_daily_budget(self.daily_budget)
        return not allowed

    def _check_daily_budget_exceeded(self) -> bool:
        if self.config.slack.daily_budget_usd is None:
            return False
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state.daily_reset_date != today:
            return False
        return self._state.daily_spend_usd >= self.config.slack.daily_budget_usd

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        """Core scheduling loop — runs until stop is requested."""
        while not self._stop_event.is_set():
            # Check max_hours
            if self.max_hours:
                elapsed = (time.monotonic() - self._started_at) / 3600
                if elapsed >= self.max_hours:
                    logger.info(
                        "Max hours (%.1f) reached, shutting down", self.max_hours
                    )
                    break

            try:
                self._tick()
            except Exception:
                logger.exception("Error in daemon main loop tick")

            self._stop_event.wait(timeout=_MAIN_LOOP_INTERVAL)

    def _tick(self) -> None:
        """Single iteration of the main scheduling loop."""
        now = time.monotonic()
        executed_item = False

        # 1. Try to execute next queue item
        if not self._pipeline_running:
            executed_item = self._try_execute_next()

        # 2. GitHub polling
        poll_interval = self.daemon_config.github_poll_interval_seconds
        if now - self._last_github_poll_time >= poll_interval:
            self._poll_github_issues()
            self._last_github_poll_time = now

        # 3. CEO idle-fill (only when healthy, queue is empty, and no pipeline running)
        ceo_cooldown = self.daemon_config.ceo_cooldown_minutes * 60
        if (
            not executed_item
            and not self._pipeline_running
            and not self._state.is_circuit_breaker_active()
            and not self._state.paused
            and self._pending_count() == 0
            and now - self._last_ceo_time >= ceo_cooldown
        ):
            self._schedule_ceo()
            self._last_ceo_time = now

        # 4. Cleanup scheduling (skip when degraded)
        cleanup_interval = self.daemon_config.cleanup_interval_hours * 3600
        if (
            not self._state.is_circuit_breaker_active()
            and not self._state.paused
            and now - self._last_cleanup_time >= cleanup_interval
        ):
            self._schedule_cleanup()
            self._last_cleanup_time = now

        # 4.5 Active reprioritization
        if now - self._last_reprioritize_time >= 900:
            self._reprioritize_queue()
            self._last_reprioritize_time = now

        # 5. Heartbeat
        heartbeat_interval = self.daemon_config.heartbeat_interval_minutes * 60
        if now - self._last_heartbeat_time >= heartbeat_interval:
            self._post_heartbeat()
            self._last_heartbeat_time = now
        self._post_daily_digest_if_due()

        # 6. PR outcome polling
        outcome_interval = self.daemon_config.outcome_poll_interval_minutes * 60
        if now - self._last_outcome_poll_time >= outcome_interval:
            self._poll_pr_outcomes()
            self._last_outcome_poll_time = now

        # 7. PR sync — keep ColonyOS PRs up-to-date with main
        pr_sync_cfg = self.daemon_config.pr_sync
        if (
            pr_sync_cfg.enabled
            and not self._state.paused
            and not self._pipeline_running
            and now - self._last_pr_sync_time >= pr_sync_cfg.interval_minutes * 60
        ):
            if self._sync_stale_prs():
                self._last_pr_sync_time = now

    # ------------------------------------------------------------------
    # Queue execution
    # ------------------------------------------------------------------

    def _try_execute_next(self) -> bool:
        """Pop the highest-priority pending item and execute it."""
        with self._lock:
            if self._state.paused:
                return False

            # Budget check (reset alert flags if daily counters were reset)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._state.daily_reset_date != today:
                self._budget_80_alerted = False
                self._budget_100_alerted = False
                self._last_budget_incident_date = None

            allowed, remaining = self._state.check_daily_budget(self.daily_budget)

            # Budget threshold alerts
            spend = self._state.daily_spend_usd
            if self.daily_budget is not None and self.daily_budget > 0:
                pct = spend / self.daily_budget
                if pct >= 1.0 and not self._budget_100_alerted:
                    self._budget_100_alerted = True
                    self._post_slack_message(
                        f":red_circle: Budget exhausted — ${spend:.2f}/${self.daily_budget:.2f} "
                        f"(100%). Daemon will not execute further items today."
                    )
                elif pct >= 0.8 and not self._budget_80_alerted:
                    self._budget_80_alerted = True
                    self._post_slack_message(
                        f":warning: Budget warning — ${spend:.2f}/${self.daily_budget:.2f} "
                        f"({pct:.0%} used). Approaching daily limit."
                    )

            if not allowed:
                pending = sum(
                    1
                    for queued_item in self._queue_state.items
                    if queued_item.status == QueueItemStatus.PENDING
                )
                incident_path = self._maybe_record_budget_incident(today=today, pending=pending)
                guidance = self._budget_exhaustion_guidance(incident_path=incident_path)
                logger.warning(
                    "Daily budget exhausted; queue remains idle (spent=$%.2f, cap=%s, pending=%d). %s",
                    self._state.daily_spend_usd,
                    self._budget_cap_label(),
                    pending,
                    guidance,
                )
                return False

            # Circuit breaker check
            if self._state.is_circuit_breaker_active():
                logger.debug("Circuit breaker active, skipping execution")
                return False

            # Find highest-priority pending item
            item = self._next_pending_item()
            if item is None:
                return False

        # Only inspect or recover git state when there is actual runnable work.
        # This avoids mutating the repo while the daemon is paused, cooling down,
        # or simply idle with an empty queue.
        worktree_state, worktree_detail = self._preexec_worktree_state()
        if worktree_state == "indeterminate":
            logger.error(
                "Pre-execution worktree check failed (fail-closed); blocking execution: %s",
                worktree_detail,
            )
            self._pause_for_pre_execution_blocker(
                item,
                "Could not run `git status` to verify the worktree (fail-closed). "
                f"{worktree_detail} "
                "Fix git access from the daemon's repo root (permissions, install, or hung/broken repo), "
                "confirm `git status --porcelain` succeeds, then resume.",
            )
            return False
        if worktree_state == "dirty":
            if self.daemon_config.auto_recover_dirty_worktree:
                logger.warning("Dirty worktree detected pre-execution, auto-recovering")
                if not self._recover_dirty_worktree_preemptive():
                    self._pause_for_pre_execution_blocker(
                        item,
                        "Dirty worktree before execution: auto-recovery failed. "
                        "Execution is blocked until the worktree is fixed; then resume the daemon.",
                    )
                    return False
            else:
                logger.error(
                    "Dirty worktree detected, skipping execution. "
                    "Enable auto_recover_dirty_worktree or clean manually."
                )
                self._pause_for_pre_execution_blocker(
                    item,
                    "Dirty worktree before execution while `daemon.auto_recover_dirty_worktree` "
                    "is disabled. Execution is blocked until the worktree is clean or auto "
                    "recovery is enabled; then resume the daemon.",
                )
                return False

        with self._lock:
            if self._state.paused or self._state.is_circuit_breaker_active():
                return False
            if item.status != QueueItemStatus.PENDING:
                return False
            item.status = QueueItemStatus.RUNNING
            item.started_at = datetime.now(timezone.utc).isoformat()
            self._pipeline_running = True
            self._pipeline_started_at = time.monotonic()
            # Reset stall flag — it stays True after recovery until the next
            # pipeline run so /healthz can report the stall that just happened.
            self._pipeline_stalled = False
            self._current_running_item = item
            self._persist_queue()

        # Execute outside the lock
        try:
            log = self._execute_item(item)
            with self._lock:
                item.run_id = log.run_id
                item.cost_usd = log.total_cost_usd
                item.pr_url = log.pr_url
                if log.branch_name:
                    item.branch_name = log.branch_name
                if log.preflight and log.preflight.head_sha:
                    item.head_sha = log.preflight.head_sha
                if log.status == RunStatus.COMPLETED:
                    item.status = QueueItemStatus.COMPLETED
                    self._state.record_success()
                    self._recent_failure_codes.clear()
                else:
                    item.status = QueueItemStatus.FAILED
                    item.error = (
                        log.phases[-1].error[:200]
                        if log.phases and log.phases[-1].error
                        else "Pipeline failed"
                    )
                self._state.record_spend(log.total_cost_usd)
                self._pipeline_running = False
                self._pipeline_started_at = None
                self._current_running_item = None
                self._persist_state()
                self._persist_queue()
                logger.info(
                    "Finished item %s (status=%s, cost=$%.4f, spend=%s, pending=%d)",
                    item.id,
                    item.status.value,
                    log.total_cost_usd,
                    self._spent_summary(),
                    sum(
                        1
                        for queued_item in self._queue_state.items
                        if queued_item.status == QueueItemStatus.PENDING
                    ),
                )
            self._cleanup_notification_lock(item.id)
        except KeyboardInterrupt:
            logger.warning("Run interrupted while executing item %s", item.id)
            with self._lock:
                item.status = QueueItemStatus.FAILED
                item.error = "Run interrupted by user (Ctrl+C)"
                self._pipeline_running = False
                self._pipeline_started_at = None
                self._current_running_item = None
                self._persist_state()
                self._persist_queue()
            self._cleanup_notification_lock(item.id)
            raise
        except Exception as exc:
            logger.exception("Pipeline failed for item %s", item.id)
            failure_message = self._failure_summary(exc)
            incident_path = self._record_runtime_incident(
                label_prefix=f"daemon-item-{item.source_type}",
                summary=(
                    f"Queue item {item.id} failed while executing in daemon mode.\n\n"
                    f"Source type: {item.source_type}\n"
                    f"Source value: {item.source_value[:500]}\n"
                    f"Failure: {failure_message}\n"
                    f"Hint: {self._failure_guidance(exc)}"
                ),
                metadata={
                    "item_id": item.id,
                    "source_type": item.source_type,
                    "source_value": item.source_value[:500],
                    "error": failure_message,
                    "daily_spend_usd": self._state.daily_spend_usd,
                    "daily_budget": self.daily_budget,
                },
            )
            operator_hint = self._failure_guidance(exc)
            error_code = getattr(exc, "code", None) or type(exc).__name__
            systemic_slack: tuple[str, int] | None = None
            escalation_slack: tuple[int, int] | None = None
            cb_cooldown_slack: tuple[int, int, str] | None = None
            with self._lock:
                item.status = QueueItemStatus.FAILED
                item.error = self._format_item_error(
                    failure_message,
                    incident_path=incident_path,
                )
                self._recent_failure_codes.append(error_code)
                max_tracked = self.daemon_config.max_consecutive_failures
                if len(self._recent_failure_codes) > max_tracked:
                    self._recent_failure_codes = self._recent_failure_codes[-max_tracked:]

                failures = self._state.record_failure()
                if failures >= max_tracked:
                    if self._is_systemic_failure():
                        self._state.paused = True
                        logger.error(
                            "Auto-paused: %d consecutive failures with same error (%s). "
                            "Send 'resume' in the configured Slack channel to unpause.",
                            failures,
                            error_code,
                        )
                        self._state.circuit_breaker_until = None
                        systemic_slack = (error_code, failures)
                    else:
                        cb_expiry = self._state.activate_circuit_breaker(
                            self.daemon_config.circuit_breaker_cooldown_minutes
                        )
                        activation_n = self._state.circuit_breaker_activations
                        if cb_expiry is None:
                            self._state.paused = True
                            logger.error(
                                "Auto-paused: circuit breaker escalated after %d activations",
                                activation_n,
                            )
                            self._state.circuit_breaker_until = None
                            escalation_slack = (activation_n, failures)
                        else:
                            logger.warning(
                                "Circuit breaker activated after %d consecutive failures "
                                "(activation #%d, cooldown until %s)",
                                failures,
                                activation_n,
                                cb_expiry,
                            )
                            cb_cooldown_slack = (failures, activation_n, cb_expiry)
                self._pipeline_running = False
                self._pipeline_started_at = None
                self._current_running_item = None
                self._persist_state()
                self._persist_queue()
            if systemic_slack is not None:
                self._post_systemic_failure_alert(*systemic_slack)
            if escalation_slack is not None:
                self._post_circuit_breaker_escalation_pause_alert(*escalation_slack)
            if cb_cooldown_slack is not None:
                self._post_circuit_breaker_cooldown_notice(*cb_cooldown_slack)
            logger.error(
                "Daemon item %s failed: %s. %s",
                item.id,
                failure_message,
                operator_hint,
            )
            self._post_execution_failure(
                item,
                failure_message=failure_message,
                incident_path=str(incident_path) if incident_path is not None else None,
            )
            self._cleanup_notification_lock(item.id)
        return True

    def _make_monitor_ui(
        self,
        prefix: str = "",
        *,
        badge: Any | None = None,
        task_id: str | None = None,
    ) -> Any | None:
        if not self._monitor_mode:
            return None
        if badge is None and task_id is not None:
            from colonyos.ui import make_task_badge

            badge = make_task_badge(task_id)
        return _DaemonMonitorEventUI(
            prefix=prefix,
            badge_text=getattr(badge, "text", ""),
            badge_style=getattr(badge, "style", ""),
        )

    def _next_pending_item(self) -> QueueItem | None:
        """Return the highest-priority pending item (lowest priority number, FIFO within tier)."""
        item = select_next_pending_item(self._queue_state)
        if item is not None:
            self._persist_queue()
        return item

    def _execute_item(self, item: QueueItem) -> RunLog:
        """Execute a single queue item through the pipeline.

        Returns the full run log.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would execute item %s: %s", item.id, item.source_value[:100])
            log = RunLog(run_id=item.id, prompt=item.source_value, status=RunStatus.COMPLETED)
            log.mark_finished()
            return log

        logger.info(
            "Executing item %s (type=%s, priority=%d)",
            item.id,
            item.source_type,
            item.priority,
        )

        # Import here to avoid circular imports — cli.py imports from many modules
        from colonyos.cli import _queue_item_branch_name_override
        from colonyos.slack import (
            FanoutSlackUI,
            SlackUI,
            format_phase_breakdown_line,
            post_message,
            post_run_summary,
        )
        from colonyos.ui import NullUI

        branch_override = _queue_item_branch_name_override(item, self.config)
        if branch_override and item.branch_name != branch_override:
            with self._lock:
                item.branch_name = branch_override
                self._persist_queue()

        notification = self._ensure_notification_thread(
            item,
            f":gear: *Starting {item.source_type} work*\n{item.summary or item.source_value[:160]}",
        )
        targets = notification_targets(item)
        ui_factory = None
        if notification is not None and targets:
            client, channel, thread_ts = notification

            def _slack_ui_factory(
                prefix: str = "",
                *,
                badge: Any | None = None,
                task_id: str | None = None,
            ) -> Any:
                is_nested_stream = badge is not None or task_id is not None or bool(prefix)
                slack_targets = [SlackUI(client, target_channel, target_ts) for target_channel, target_ts in targets]
                slack_ui: Any
                if len(slack_targets) == 1:
                    slack_ui = slack_targets[0]
                else:
                    slack_ui = FanoutSlackUI(*slack_targets)
                monitor_ui = self._make_monitor_ui(prefix, badge=badge, task_id=task_id)
                if is_nested_stream:
                    return monitor_ui if monitor_ui is not None else NullUI()
                if monitor_ui is not None:
                    return _CombinedUI(monitor_ui, slack_ui)
                return slack_ui

            ui_factory = _slack_ui_factory
            try:
                for target_channel, target_ts in targets:
                    post_message(
                        client,
                        target_channel,
                        (
                            f":rocket: Working on *{item.source_type}* request\n"
                            f"{item.summary or item.issue_title or item.source_value[:200]}"
                        ),
                        thread_ts=target_ts,
                    )
            except Exception:
                logger.debug("Failed to post queue execution start", exc_info=True)
        elif self._monitor_mode:
            ui_factory = self._make_monitor_ui

        log = self._run_pipeline_for_item(item, ui_factory=ui_factory)
        item.run_id = log.run_id
        item.pr_url = log.pr_url
        if log.branch_name:
            item.branch_name = log.branch_name
        if log.preflight and log.preflight.head_sha:
            item.head_sha = log.preflight.head_sha

        if notification is not None and targets:
            client, channel, thread_ts = notification
            try:
                for target_channel, target_ts in targets:
                    post_run_summary(
                        client,
                        target_channel,
                        target_ts,
                        status=log.status.value,
                        total_cost=log.total_cost_usd,
                        branch_name=log.branch_name,
                        pr_url=log.pr_url,
                        summary=item.summary,
                        phase_breakdown=[format_phase_breakdown_line(phase) for phase in log.phases],
                        demand_count=item.demand_count,
                    )
            except Exception:
                logger.debug("Failed to post final queue summary", exc_info=True)
        return log

    # ------------------------------------------------------------------
    # GitHub Issue Polling (FR-2)
    # ------------------------------------------------------------------

    def _poll_github_issues(self) -> None:
        """Poll for new GitHub issues and enqueue them."""
        try:
            from colonyos.github import fetch_open_issues

            issues = fetch_open_issues(self.repo_root)
            label_filter = set(self.daemon_config.issue_labels)

            from colonyos.sanitize import sanitize_untrusted_content

            for issue in issues:
                # Label filtering
                if label_filter:
                    issue_labels = {lbl.lower() for lbl in issue.labels}
                    if not label_filter.intersection(issue_labels):
                        continue

                # Dedup check
                if self._is_duplicate("issue", str(issue.number)):
                    continue
                similar = find_similar_queue_item(
                    self._queue_state,
                    source_type="issue",
                    prompt_text=issue.title,
                )
                if similar is not None:
                    with self._lock:
                        attach_demand_signal(
                            similar.item,
                            source_type="issue",
                            source_value=str(issue.number),
                            summary=issue.title,
                        )
                        reprioritize_queue_item(similar.item)
                        self._persist_queue()
                    logger.info(
                        "Merged GitHub issue #%d into existing queue item %s",
                        issue.number,
                        similar.item.id,
                    )
                    continue

                priority = compute_priority("issue", issue.labels)
                item = QueueItem(
                    id=f"issue-{issue.number}-{int(time.time())}",
                    source_type="issue",
                    source_value=str(issue.number),
                    status=QueueItemStatus.PENDING,
                    priority=priority,
                    issue_title=sanitize_untrusted_content(issue.title),
                    summary=sanitize_untrusted_content(issue.title),
                    priority_reason="base:issue",
                    notification_channel=self._default_notification_channel(),
                    related_item_ids=[
                        related.id
                        for related in find_related_history_items(
                            self._queue_state,
                            prompt_text=issue.title,
                        )
                    ],
                )
                reprioritize_queue_item(item)

                with self._lock:
                    self._queue_state.items.append(item)
                    self._persist_queue()
                    self._post_queue_enqueued(item)

                logger.info(
                    "Enqueued GitHub issue #%d (P%d): %s",
                    issue.number,
                    priority,
                    issue.title,
                )

        except Exception:
            logger.exception("Error polling GitHub issues")

    def _poll_pr_outcomes(self) -> None:
        """Poll GitHub for PR outcome updates.

        Wraps :func:`~colonyos.outcomes.poll_outcomes` in try/except so
        a failure never crashes the daemon.  The next scheduled poll is
        the implicit retry — no explicit retry logic.
        """
        try:
            from colonyos.outcomes import poll_outcomes

            poll_outcomes(self.repo_root)
            logger.debug("PR outcome poll completed")
        except Exception:
            logger.warning("Error polling PR outcomes", exc_info=True)

    def _sync_stale_prs(self) -> bool:
        """Sync a stale ColonyOS PR with main (concern #7).

        Wraps :func:`~colonyos.pr_sync.sync_stale_prs` in try/except so
        a failure never crashes the daemon.  Follows the same pattern as
        :meth:`_poll_pr_outcomes`.

        Returns ``True`` if the call completed without exception (regardless
        of whether a sync was performed), ``False`` on exception.
        """
        try:
            from colonyos.pr_sync import sync_stale_prs

            sync_stale_prs(
                repo_root=self.repo_root,
                config=self.config,
                queue_state_items=self._queue_state.items,
                post_slack_fn=self._post_slack_message,
                write_enabled=self.daemon_config.dashboard_write_enabled,
            )
            logger.debug("PR sync check completed")
            return True
        except Exception:
            logger.warning("Error during PR sync", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # CEO Idle-Fill (FR-4)
    # ------------------------------------------------------------------

    def _schedule_ceo(self) -> None:
        """Run CEO cycle to propose work when queue is idle."""
        if self.dry_run:
            logger.info("[DRY RUN] Would run CEO idle-fill cycle")
            return

        try:
            logger.info("Running CEO idle-fill cycle")
            from colonyos.orchestrator import run_ceo
            ui = self._make_monitor_ui("CEO ")
            if ui is None:
                from colonyos.ui import PhaseUI
                ui = PhaseUI(verbose=self.verbose, prefix="CEO ")

            with self._agent_lock:
                proposal_prompt, phase_result = run_ceo(
                    repo_root=self.repo_root,
                    config=self.config,
                    ui=ui,
                )

            if not phase_result.success:
                logger.warning(
                    "CEO idle-fill failed: %s",
                    phase_result.error or "unknown CEO error",
                )
                return

            if proposal_prompt:
                similar = find_similar_queue_item(
                    self._queue_state,
                    source_type="ceo",
                    prompt_text=proposal_prompt,
                )
                if similar is not None:
                    with self._lock:
                        attach_demand_signal(
                            similar.item,
                            source_type="ceo",
                            source_value=proposal_prompt,
                            summary=proposal_prompt.splitlines()[0][:180],
                        )
                        reprioritize_queue_item(similar.item)
                        self._persist_queue()
                    logger.info(
                        "Merged CEO proposal into existing queue item %s",
                        similar.item.id,
                    )
                    return
                item = QueueItem(
                    id=f"ceo-{int(time.time())}",
                    source_type="ceo",
                    source_value=proposal_prompt,
                    status=QueueItemStatus.PENDING,
                    priority=compute_priority("ceo"),
                    summary=proposal_prompt.splitlines()[0][:180],
                    priority_reason="base:ceo",
                    notification_channel=self._default_notification_channel(),
                    related_item_ids=[
                        related.id
                        for related in find_related_history_items(
                            self._queue_state,
                            prompt_text=proposal_prompt,
                        )
                    ],
                )
                reprioritize_queue_item(item)
                with self._lock:
                    self._queue_state.items.append(item)
                    self._persist_queue()
                    self._post_queue_enqueued(item)
                logger.info("CEO proposed work enqueued (P%d): %s", item.priority, proposal_prompt[:120])
            else:
                logger.info("CEO idle-fill produced no actionable proposal")

        except Exception:
            logger.exception("Error in CEO idle-fill cycle")

    # ------------------------------------------------------------------
    # Cleanup Scheduling (FR-5)
    # ------------------------------------------------------------------

    def _schedule_cleanup(self) -> None:
        """Schedule cleanup tasks."""
        try:
            from colonyos.cleanup import list_merged_branches, scan_directory

            # Run branch cleanup directly (non-queued, fast operation)
            branches = list_merged_branches(
                self.repo_root, prefix=self.config.branch_prefix
            )
            if branches:
                logger.info("Found %d merged branches for cleanup", len(branches))

            # Scan for complexity candidates → enqueue as cleanup items
            candidates = scan_directory(
                self.repo_root / "src",
                max_lines=self.config.cleanup.scan_max_lines,
                max_functions=self.config.cleanup.scan_max_functions,
            )

            enqueued = 0
            max_items = self.daemon_config.max_cleanup_items
            for candidate in candidates[:max_items]:
                source_val = str(candidate.path)
                if self._is_duplicate("cleanup", source_val):
                    continue

                item = QueueItem(
                    id=f"cleanup-{int(time.time())}-{enqueued}",
                    source_type="cleanup",
                    source_value=source_val,
                    status=QueueItemStatus.PENDING,
                    priority=compute_priority("cleanup"),
                    summary=f"Cleanup/refactor {Path(candidate.path).name}",
                    priority_reason="base:cleanup",
                    notification_channel=self._default_notification_channel(),
                )
                reprioritize_queue_item(item)
                with self._lock:
                    self._queue_state.items.append(item)
                    enqueued += 1

            if enqueued:
                with self._lock:
                    self._persist_queue()
                    for item in self._queue_state.items:
                        if item.source_type == "cleanup" and item.status == QueueItemStatus.PENDING and not item.notification_thread_ts:
                            self._post_queue_enqueued(item)
                logger.info("Enqueued %d cleanup items", enqueued)

        except Exception:
            logger.exception("Error in cleanup scheduling")

    # ------------------------------------------------------------------
    # Health & Observability (FR-10)
    # ------------------------------------------------------------------

    def _reprioritize_queue(self) -> None:
        try:
            from colonyos.models import QueueState
            from colonyos.prioritizer import apply_priority_decisions, score_queue_with_agent

            with self._lock:
                snapshot = QueueState.from_dict(self._queue_state.to_dict())
            with self._agent_lock:
                decisions = score_queue_with_agent(
                    self.repo_root,
                    self.config,
                    snapshot,
                    ui=self._make_monitor_ui("Priority "),
                )
            if not decisions:
                return
            with self._lock:
                changed = apply_priority_decisions(self._queue_state, decisions)
                if changed:
                    self._persist_queue()
        except Exception:
            logger.warning("Queue reprioritization failed", exc_info=True)

    def _post_daily_digest_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if now.hour < self.daemon_config.digest_hour_utc:
            return
        if self._last_digest_date == today:
            return

        top_items = pending_queue_snapshot(self._queue_state, limit=3)
        pending = sum(
            1 for item in self._queue_state.items
            if item.status == QueueItemStatus.PENDING
        )
        recent_completed = [
            item for item in reversed(self._queue_state.items)
            if item.status == QueueItemStatus.COMPLETED
        ][:3]
        lines = [
            ":spiral_note_pad: *Daily ColonyOS Queue Digest*",
            f"Queue depth: {pending}",
            "Top 3 pending:",
        ]
        if top_items:
            for item in top_items:
                lines.append(
                    f"- P{item.priority} {item.source_type}: "
                    f"{item.summary or item.issue_title or item.source_value[:140]}"
                )
                if item.priority_reason:
                    lines.append(f"  reason: {item.priority_reason}")
        else:
            lines.append("- No pending work.")
        if recent_completed:
            lines.append("Recent completions:")
            for item in recent_completed:
                lines.append(
                    f"- {item.source_type}: {item.summary or item.issue_title or item.source_value[:100]}"
                )
        lines.append(f"Daily spend: {self._spent_summary()}")
        self._post_slack_message("\n".join(lines))
        self._last_digest_date = today

    def _post_heartbeat(self) -> None:
        """Post heartbeat to Slack and update state."""
        with self._lock:
            self._state.touch_heartbeat()
            self._persist_state()
            items_today = self._state.total_items_today
            spend = self._state.daily_spend_usd

        logger.info(
            "Heartbeat: %d items today, %s, pending=%d",
            items_today,
            self._spent_summary(spend=spend),
            sum(
                1 for i in self._queue_state.items
                if i.status == QueueItemStatus.PENDING
            ),
        )

        pending = sum(
            1 for i in self._queue_state.items
            if i.status == QueueItemStatus.PENDING
        )
        spend_label = (
            f"${spend:.2f}/unlimited"
            if self.daily_budget is None
            else f"${spend:.2f}/${self.daily_budget:.2f}"
        )
        msg = (
            f":heartbeat: *ColonyOS Heartbeat*\n"
            f"Items today: {items_today} | Spend: {spend_label} | "
            f"Queue depth: {pending} | Paused: {self._state.paused}"
        )
        self._post_slack_message(msg)

    # ------------------------------------------------------------------
    # Crash Recovery (FR-8)
    # ------------------------------------------------------------------

    def _recover_from_crash(self) -> None:
        """Scan for orphaned RUNNING items and mark them as FAILED."""
        recovered = 0
        for item in self._queue_state.items:
            if item.status == QueueItemStatus.RUNNING:
                item.status = QueueItemStatus.FAILED
                item.error = "daemon crash recovery"
                recovered += 1

        if recovered:
            logger.warning(
                "Crash recovery: marked %d orphaned RUNNING items as FAILED",
                recovered,
            )
            self._persist_queue()

        # Ensure clean git state
        try:
            from colonyos.recovery import git_status_porcelain, preserve_and_reset_worktree

            dirty = git_status_porcelain(self.repo_root)
            if dirty.strip():
                logger.warning("Dirty git state on startup, preserving and resetting")
                preserve_result = preserve_and_reset_worktree(
                    self.repo_root,
                    "daemon_crash_recovery",
                )
                incident_path = self._record_runtime_incident(
                    label_prefix="daemon-startup-recovery",
                    summary=(
                        "Daemon startup found a dirty worktree and preserved it before reset.\n\n"
                        f"Preservation mode: {preserve_result.preservation_mode}\n"
                        f"Snapshot dir: {preserve_result.snapshot_dir}\n"
                        f"Stash message: {preserve_result.stash_message or '(none)'}\n"
                        "Inspect the snapshot and incident file before replaying lost work."
                    ),
                    metadata={
                        "preservation_mode": preserve_result.preservation_mode,
                        "snapshot_dir": str(preserve_result.snapshot_dir),
                        "stash_message": preserve_result.stash_message,
                        "dirty_output": dirty,
                    },
                )
                logger.warning(
                    "Startup recovery preserved dirty worktree state at %s (mode=%s)",
                    incident_path,
                    preserve_result.preservation_mode,
                )
        except Exception:
            logger.exception("Error during git state recovery")

    def _preexec_worktree_state(
        self,
    ) -> tuple[Literal["clean", "dirty", "indeterminate"], str]:
        """Classify worktree before execution: clean, dirty, or indeterminate (fail-closed).

        Uses the same rules as pipeline preflight (including ignoring ColonyOS output dirs).
        If ``git status`` errors or times out, returns ``indeterminate`` with a short detail
        string instead of assuming clean.
        """
        from colonyos.orchestrator import _check_working_tree_clean

        try:
            is_clean, _dirty_out = _check_working_tree_clean(self.repo_root)
            return ("clean" if is_clean else "dirty", "")
        except PreflightError as exc:
            return ("indeterminate", str(exc).strip() or exc.__class__.__name__)

    def _recover_dirty_worktree_preemptive(self) -> bool:
        """Preserve and reset a dirty worktree before any item is picked.

        Returns True if recovery succeeded and execution can proceed,
        False if recovery failed and execution should be skipped.
        """
        try:
            from colonyos.recovery import preserve_and_reset_worktree

            preserve_result = preserve_and_reset_worktree(
                self.repo_root,
                "daemon-preexec-dirty-recovery",
            )
            self._record_runtime_incident(
                label_prefix="daemon-preexec-dirty-recovery",
                summary=(
                    "Pre-execution check found a dirty worktree. "
                    "State was preserved and the worktree was reset.\n\n"
                    f"Preservation mode: {preserve_result.preservation_mode}\n"
                    f"Snapshot dir: {preserve_result.snapshot_dir}\n"
                    f"Stash message: {preserve_result.stash_message or '(none)'}"
                ),
                metadata={
                    "preservation_mode": preserve_result.preservation_mode,
                    "snapshot_dir": str(preserve_result.snapshot_dir),
                    "stash_message": preserve_result.stash_message,
                },
            )
            logger.info(
                "Pre-execution dirty worktree recovered (mode=%s)",
                preserve_result.preservation_mode,
            )
            return True
        except Exception:
            logger.exception("Failed to recover dirty worktree pre-execution")
            return False

    def _should_auto_recover_dirty_worktree(self, exc: Exception) -> bool:
        return (
            self.daemon_config.auto_recover_dirty_worktree
            and isinstance(exc, PreflightError)
            and exc.code == "dirty_worktree"
        )

    @staticmethod
    def _should_auto_recover_existing_branch(exc: Exception) -> bool:
        if not isinstance(exc, PreflightError) or exc.code != "branch_exists":
            return False
        details = exc.details or {}
        if details.get("open_pr_number") is not None:
            return False
        return bool(details.get("branch_name"))

    def _recover_existing_branch_and_retry(
        self,
        item: QueueItem,
        exc: PreflightError,
    ) -> None:
        branch_name = (exc.details or {}).get("branch_name", "")
        logger.warning(
            "Branch '%s' blocked item %s; deleting stale local branch and retrying",
            branch_name,
            item.id,
        )
        try:
            result = subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.repo_root,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git branch -D {branch_name} failed: {result.stderr.strip()}"
                )
            logger.info("Deleted stale branch '%s'; retrying item %s", branch_name, item.id)
        except Exception:
            logger.exception("Failed to delete stale branch '%s'", branch_name)
            raise exc from None

    def _recover_dirty_worktree_and_retry(
        self,
        item: QueueItem,
        exc: PreflightError,
    ) -> None:
        from colonyos.recovery import incident_slug, preserve_and_reset_worktree

        dirty_output = str(exc.details.get("dirty_output", "")).strip()
        recovery_label = incident_slug(f"daemon-dirty-worktree-{item.id}")
        logger.warning(
            "Dirty worktree blocked item %s; preserving state and retrying once",
            item.id,
        )
        preserve_result = preserve_and_reset_worktree(self.repo_root, recovery_label)
        incident_path = self._record_runtime_incident(
            label_prefix="daemon-dirty-worktree-recovery",
            summary=(
                "Daemon queue execution hit a dirty-worktree preflight failure and "
                "automatically preserved state before retrying.\n\n"
                f"Item: {item.id}\n"
                f"Source type: {item.source_type}\n"
                f"Preservation mode: {preserve_result.preservation_mode}\n"
                f"Snapshot dir: {preserve_result.snapshot_dir}\n"
                f"Stash message: {preserve_result.stash_message or '(none)'}\n"
                "The daemon will retry this item once on the cleaned worktree."
            ),
            metadata={
                "item_id": item.id,
                "source_type": item.source_type,
                "source_value": item.source_value[:500],
                "preservation_mode": preserve_result.preservation_mode,
                "snapshot_dir": str(preserve_result.snapshot_dir),
                "stash_message": preserve_result.stash_message,
                "dirty_output": dirty_output,
            },
        )
        logger.warning(
            "Dirty worktree recovery preserved item %s state at %s (mode=%s); retrying",
            item.id,
            incident_path,
            preserve_result.preservation_mode,
        )

    def _run_pipeline_for_item(
        self,
        item: QueueItem,
        *,
        ui_factory: Any = None,
    ) -> RunLog:
        from colonyos.cli import run_pipeline_for_queue_item

        timeout = self.daemon_config.pipeline_timeout_seconds
        timed_out = threading.Event()

        def _timeout_watchdog() -> None:
            logger.warning(
                "Pipeline timeout (%ds) reached for item %s, requesting cancellation",
                timeout,
                item.id,
            )
            timed_out.set()
            from colonyos.agent import request_active_phase_cancel

            cancelled = request_active_phase_cancel(
                f"Pipeline exceeded {timeout}s wall-clock timeout"
            )
            if not cancelled:
                from colonyos.cancellation import request_cancel

                request_cancel(
                    f"Pipeline exceeded {timeout}s wall-clock timeout"
                )

        # Capture the current branch so we can restore after the pipeline
        # finishes (success or failure).  This prevents a failed pipeline
        # from leaving the daemon stranded on a feature branch.
        branch_before: str | None = None
        try:
            br = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=self.repo_root, timeout=10,
            )
            name = br.stdout.strip() if br.returncode == 0 else ""
            # "HEAD" means detached -- not a real branch we can restore to.
            if name and name != "HEAD":
                branch_before = name
        except Exception:
            logger.debug("Could not determine current branch before pipeline run")

        attempted_dirty_worktree_recovery = False
        attempted_branch_exists_recovery = False
        watchdog = threading.Timer(timeout, _timeout_watchdog)
        watchdog.daemon = True
        watchdog.start()
        try:
            while True:
                if timed_out.is_set():
                    raise RuntimeError(
                        f"Pipeline for item {item.id} exceeded "
                        f"{timeout}s wall-clock timeout"
                    )
                try:
                    with self._agent_lock:
                        result = run_pipeline_for_queue_item(
                            item=item,
                            repo_root=self.repo_root,
                            config=self.config,
                            verbose=self.verbose,
                            quiet=False,
                            ui_factory=ui_factory,
                            queue_state=self._queue_state,
                        )
                    if timed_out.is_set():
                        raise RuntimeError(
                            f"Pipeline for item {item.id} exceeded "
                            f"{timeout}s wall-clock timeout"
                        )
                    return result
                except PreflightError as exc:
                    if (
                        not attempted_dirty_worktree_recovery
                        and self._should_auto_recover_dirty_worktree(exc)
                    ):
                        attempted_dirty_worktree_recovery = True
                        self._recover_dirty_worktree_and_retry(item, exc)
                        continue
                    if (
                        not attempted_branch_exists_recovery
                        and self._should_auto_recover_existing_branch(exc)
                    ):
                        attempted_branch_exists_recovery = True
                        self._recover_existing_branch_and_retry(item, exc)
                        continue
                    raise
        finally:
            watchdog.cancel()
            # Restore the branch the daemon was on before the pipeline run.
            # The orchestrator's safety commit (in _run_pipeline finally)
            # should have already committed any dirty state, but
            # restore_to_branch handles leftover dirt as a fallback.
            if branch_before:
                try:
                    from colonyos.recovery import restore_to_branch

                    restored = restore_to_branch(self.repo_root, branch_before)
                    if restored:
                        logger.info("Post-pipeline: %s", restored)
                except Exception:
                    logger.warning(
                        "Failed to restore to %s after pipeline run",
                        branch_before,
                        exc_info=True,
                    )

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _start_threads(self) -> list[threading.Thread]:
        """Start and return daemon background threads."""
        threads: list[threading.Thread] = []

        # Slack listener thread (if enabled)
        if self.config.slack.enabled:
            t = threading.Thread(
                target=self._slack_listener_thread,
                name="daemon-slack",
                daemon=True,
            )
            t.start()
            threads.append(t)

        # Watchdog thread (always enabled)
        self._start_watchdog_thread()
        if self._watchdog_thread is not None:
            threads.append(self._watchdog_thread)

        return threads

    def _start_watchdog_thread(self) -> None:
        """Start the watchdog thread that detects stuck pipelines."""
        t = threading.Thread(
            target=self._watchdog_loop,
            name="daemon-watchdog",
            daemon=True,
        )
        t.start()
        self._watchdog_thread = t

    def _watchdog_loop(self) -> None:
        """Main watchdog loop — wakes every 30s to check for stalled pipelines."""
        while not self._stop_event.is_set():
            try:
                self._watchdog_check()
            except Exception:
                logger.exception("Watchdog check failed")
            self._stop_event.wait(30)

    def _watchdog_check(self) -> None:
        """Single watchdog check cycle. Detects stalls and triggers recovery."""
        if not self._pipeline_running:
            return

        stall_seconds = self.daemon_config.watchdog_stall_seconds

        # Check 1: Has the pipeline been running longer than the threshold?
        pipeline_started = self._pipeline_started_at
        if pipeline_started is None:
            return
        elapsed = time.monotonic() - pipeline_started
        if elapsed < stall_seconds:
            return

        # Check 2: Is the heartbeat file stale?
        heartbeat_path = self.repo_root / ".colonyos" / "runs" / "heartbeat"
        try:
            hb_mtime = heartbeat_path.stat().st_mtime
            time_since_heartbeat = time.time() - hb_mtime
        except FileNotFoundError:
            # No heartbeat file = no progress signal at all
            time_since_heartbeat = elapsed

        if time_since_heartbeat < stall_seconds:
            return

        # Both conditions met: pipeline is stalled
        self._pipeline_stalled = True
        logger.warning(
            "Watchdog: pipeline stalled for %.0fs (threshold=%ds, heartbeat_age=%.0fs)",
            elapsed,
            stall_seconds,
            time_since_heartbeat,
        )
        self._watchdog_recover(stall_duration=elapsed)

    def _watchdog_recover(self, stall_duration: float) -> None:
        """Recover from a stalled pipeline: cancel, wait, force-reset, mark FAILED."""
        item = self._current_running_item

        # Step 0: Emit monitor event for TUI consumption
        try:
            event_payload = {
                "type": "watchdog_stall_detected",
                "item_id": item.id if item is not None else None,
                "stall_duration_seconds": stall_duration,
                "action_taken": "auto_cancel",
            }
            sys.stdout.write(encode_monitor_event(event_payload) + "\n")
            sys.stdout.flush()
        except Exception:
            logger.exception("Watchdog: failed to emit monitor event")

        # Step 0.5: Post Slack alert (wrapped in try/except to avoid hanging the watchdog)
        try:
            if item is not None:
                duration_min = stall_duration / 60
                alert_msg = (
                    f"⚠️ *Stuck Pipeline Detected*\n"
                    f"Item {item.id} ({item.source_type}) running for {duration_min:.0f}m. "
                    f"No progress for {stall_duration:.0f}s. Auto-recovery initiated."
                )
            else:
                alert_msg = (
                    f"⚠️ *Stuck Pipeline Detected*\n"
                    f"No progress for {stall_duration:.0f}s. Auto-recovery initiated."
                )
            self._post_slack_message(alert_msg)
        except Exception:
            logger.exception("Watchdog: failed to post Slack alert")

        # Step 1: Request graceful phase cancellation
        logger.warning("Watchdog: requesting active phase cancel")
        try:
            request_active_phase_cancel(
                f"watchdog: no progress for {stall_duration:.0f}s"
            )
        except Exception:
            logger.exception("Watchdog: request_active_phase_cancel failed")

        # Step 2: Grace period — wait 30s for cooperative cancellation
        self._stop_event.wait(30)

        # Step 3: If still stuck, force cancel
        if self._pipeline_running:
            logger.warning("Watchdog: pipeline still running after grace period, forcing cancel")
            try:
                request_cancel(
                    f"watchdog: forced fallback cancellation after grace period ({stall_duration:.0f}s stall)"
                )
            except Exception:
                logger.exception("Watchdog: request_cancel fallback failed")

        # Step 4: Force-reset state under lock
        with self._lock:
            self._pipeline_running = False
            self._pipeline_started_at = None
            self._current_running_item = None
            if item is not None:
                item.status = QueueItemStatus.FAILED
                item.error = f"watchdog: no progress for {stall_duration:.0f}s"
            self._persist_queue()

    def _slack_listener_thread(self) -> None:
        """Run Slack Socket Mode listener."""
        try:
            from colonyos.slack import (
                create_slack_app,
                load_watch_state,
                resolve_channel_names,
                save_watch_state,
                start_socket_mode,
            )
            from colonyos.slack_queue import SlackQueueEngine

            self._slack_watch_state = self._load_or_create_daemon_watch_state()
            slack_app = create_slack_app(self.config.slack)
            auth_response = slack_app.client.auth_test()
            bot_user_id = auth_response["user_id"]
            resolved_channels = resolve_channel_names(
                slack_app.client,
                self.config.slack.channels,
            )
            self.config.slack.channels = [ch.id for ch in resolved_channels]

            def _persist_watch_state() -> None:
                assert self._slack_watch_state is not None
                save_watch_state(self.repo_root, self._slack_watch_state)

            def _publish_client(client: Any) -> None:
                self._slack_client = client

            assert self._slack_watch_state is not None
            slack_engine = SlackQueueEngine(
                repo_root=self.repo_root,
                config=self.config,
                queue_state=self._queue_state,
                watch_state=self._slack_watch_state,
                state_lock=self._lock,
                shutdown_event=self._stop_event,
                bot_user_id=bot_user_id,
                slack_client_ready=self._slack_client_ready,
                publish_client=_publish_client,
                persist_queue=self._persist_queue,
                persist_watch_state=_persist_watch_state,
                is_time_exceeded=self._check_time_exceeded,
                is_budget_exceeded=self._check_budget_exceeded,
                is_daily_budget_exceeded=self._check_daily_budget_exceeded,
                dry_run=self.dry_run,
                # agent_lock is passed for potential future use (e.g., multi-worker
                # triage serialization) but is NOT acquired during triage — triage
                # runs lock-free so Slack intake is never blocked by pipeline execution.
                agent_lock=self._agent_lock,
            )
            logger.info("Slack listener thread started")
            self._register_daemon_commands(slack_app)
            slack_engine.register(slack_app)
            _persist_watch_state()
            handler = start_socket_mode(slack_app)
            handler.connect()
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=5.0)
            try:
                handler.close()
            except Exception:
                logger.debug("Failed to close daemon Slack handler", exc_info=True)
        except Exception:
            logger.exception("Slack listener thread failed")

    def _make_daemon_watch_state(self) -> Any:
        from colonyos.slack import SlackWatchState

        return SlackWatchState(watch_id=_DAEMON_WATCH_ID)

    def _load_or_create_daemon_watch_state(self) -> Any:
        from colonyos.slack import load_watch_state

        return load_watch_state(self.repo_root, _DAEMON_WATCH_ID) or self._make_daemon_watch_state()

    def _register_daemon_commands(self, slack_app: Any) -> None:
        """Register message handler on the Slack app for daemon control commands."""
        control_keywords = {"pause", "stop", "halt", "resume", "start", "status"}

        @slack_app.event("message")
        def _handle_message(event: dict, say: Any) -> None:  # noqa: ANN401
            text = (event.get("text") or "").strip().lower()
            user_id = event.get("user", "")
            if text not in control_keywords:
                return
            result = self._handle_control_command(user_id, text)
            if result:
                say(result)

    # ------------------------------------------------------------------
    # Slack helpers & kill switch (FR-11)
    # ------------------------------------------------------------------

    def _post_slack_message(self, text: str) -> None:
        """Post a message to the first configured Slack channel.

        Uses ``slack_sdk.WebClient`` directly to avoid circular dependencies.
        Errors are logged and swallowed so Slack failures never block the daemon.
        """
        try:
            token = os.environ.get("COLONYOS_SLACK_BOT_TOKEN")
            if not token:
                logger.debug("No COLONYOS_SLACK_BOT_TOKEN set, skipping Slack message")
                return
            channels = self.config.slack.channels
            if not channels:
                logger.debug("No Slack channels configured, skipping Slack message")
                return
            from slack_sdk import WebClient  # imported inline to avoid hard dep

            client = WebClient(token=token)
            client.chat_postMessage(channel=channels[0], text=text)
        except Exception:
            logger.exception("Failed to post Slack message")

    def _default_notification_channel(self) -> str | None:
        channels = self.config.slack.channels
        return channels[0] if channels else None

    def _get_notification_client(self) -> Any | None:
        if self._slack_client is not None:
            return self._slack_client
        token = os.environ.get("COLONYOS_SLACK_BOT_TOKEN")
        if not token:
            return None
        try:
            from slack_sdk import WebClient

            return WebClient(token=token)
        except Exception:
            logger.debug("Failed to create Slack WebClient", exc_info=True)
            return None

    def _notification_thread_lock_for(self, item_id: str) -> threading.Lock:
        with self._notification_thread_locks_guard:
            lock = self._notification_thread_locks.get(item_id)
            if lock is None:
                lock = threading.Lock()
                self._notification_thread_locks[item_id] = lock
            return lock

    def _cleanup_notification_lock(self, item_id: str) -> None:
        """Remove the notification thread lock for a terminal item to prevent unbounded growth."""
        with self._notification_thread_locks_guard:
            self._notification_thread_locks.pop(item_id, None)

    def _ensure_notification_thread(self, item: QueueItem, intro_text: str) -> tuple[Any, str, str] | None:
        client = self._get_notification_client()
        channel = item.notification_channel or self._default_notification_channel()
        if client is None or not channel:
            return None
        if item.notification_thread_ts:
            return client, channel, item.notification_thread_ts
        item_lock = self._notification_thread_lock_for(item.id)
        with item_lock:
            with self._lock:
                if item.notification_thread_ts:
                    return client, channel, item.notification_thread_ts
            try:
                from colonyos.slack import post_message

                response = post_message(client, channel, intro_text)
            except Exception:
                logger.debug("Failed to create notification thread", exc_info=True)
                return None
            thread_ts = response.get("ts")
            if not thread_ts:
                return None
            with self._lock:
                if item.notification_thread_ts:
                    return client, channel, item.notification_thread_ts
                item.notification_channel = channel
                item.notification_thread_ts = thread_ts
                self._persist_queue()
            return client, channel, thread_ts

    def _format_phase_breakdown(self, log: Any) -> list[str]:
        from colonyos.slack import format_phase_breakdown_line

        return [format_phase_breakdown_line(phase) for phase in log.phases]

    def _post_execution_failure(
        self,
        item: QueueItem,
        *,
        failure_message: str,
        incident_path: str | None = None,
    ) -> None:
        notification = self._ensure_notification_thread(
            item,
            f":gear: *Starting {item.source_type} work*\n{item.summary or item.source_value[:160]}",
        )
        if notification is None:
            details = failure_message[:500]
            if incident_path:
                details = f"{details}\nIncident: `{incident_path}`"
            self._post_slack_message(
                f":x: *{item.source_type} failed* (`{item.id}`)\n{details}"
            )
            return
        client, channel, thread_ts = notification
        details = failure_message[:500]
        if incident_path:
            details = f"{details}\nIncident: `{incident_path}`"
        try:
            from colonyos.slack import post_message

            for target_channel, target_ts in notification_targets(item) or [(channel, thread_ts)]:
                post_message(
                    client,
                    target_channel,
                    f":x: *{item.source_type} execution failed*\n{details}",
                    thread_ts=target_ts,
                )
        except Exception:
            logger.debug("Failed to post daemon failure notification", exc_info=True)

    def _post_queue_enqueued(self, item: QueueItem) -> None:
        if item.notification_thread_ts:
            return
        summary = item.summary or item.issue_title or item.source_value[:160]
        intro = (
            f":inbox_tray: *Queued {item.source_type} work*\n"
            f"{summary}\n"
            f"Priority: P{item.priority}"
        )
        self._ensure_notification_thread(item, intro)

    def _handle_control_command(self, user_id: str, text: str) -> str | None:
        """Handle a Slack kill-switch control command.

        Returns a response string to send back, or None if the user is not
        authorized or the command is unrecognized.
        """
        allowed_ids = self.daemon_config.allowed_control_user_ids
        if not self.daemon_config.allow_all_control_users and (
            not allowed_ids or user_id not in allowed_ids
        ):
            logger.warning(
                "Unauthorized control command '%s' from user %s", text, user_id
            )
            return None

        cmd = text.strip().lower()

        if cmd in ("pause", "stop", "halt"):
            with self._lock:
                self._state.paused = True
                self._persist_state()
            logger.info("Daemon paused via Slack by user %s", user_id)
            return f"Daemon paused by <@{user_id}>."

        if cmd in ("resume", "start"):
            with self._lock:
                self._state.paused = False
                self._state.consecutive_failures = 0
                self._state.circuit_breaker_until = None
                self._state.circuit_breaker_activations = 0
                self._recent_failure_codes.clear()
                self._persist_state()
            logger.info("Daemon resumed via Slack by user %s", user_id)
            return f"Daemon resumed by <@{user_id}>."

        if cmd == "status":
            health = self.get_health()
            remaining = health["daily_budget_remaining_usd"]
            spend_line = (
                f"Spend: ${health['daily_spend_usd']:.2f} (unlimited budget)\n"
                if remaining is None
                else f"Spend: ${health['daily_spend_usd']:.2f} "
                f"(${remaining:.2f} remaining)\n"
            )
            return (
                f"*Daemon Status*\n"
                f"Status: {health['status']} | Paused: {health['paused']}\n"
                f"Queue depth: {health['queue_depth']} | Pipeline running: {health['pipeline_running']}\n"
                f"{spend_line}"
                f"Failures: {health['consecutive_failures']} | "
                f"Circuit breaker: {health['circuit_breaker_active']}"
            )

        return None

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers for graceful shutdown."""
        def _handler(signum: int, frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            logger.info("Received %s, initiating shutdown", sig_name)
            cancelled = request_cancel(f"Interrupted active work because {sig_name} was received")
            if self._pipeline_running:
                if cancelled:
                    logger.warning(
                        "Requested shared cancellation for %d active task(s) due to %s",
                        cancelled,
                        sig_name,
                    )
                logger.warning("Interrupting active pipeline due to %s", sig_name)
                raise KeyboardInterrupt(f"{sig_name} received")

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    # ------------------------------------------------------------------
    # PID lock (FR — prevent multiple instances)
    # ------------------------------------------------------------------

    def _acquire_pid_lock(self) -> None:
        """Acquire repo runtime lock and write daemon PID metadata."""
        pid_path = self.repo_root / _PID_FILE
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._runtime_guard = RepoRuntimeGuard(self.repo_root, "daemon").acquire()
        except RuntimeBusyError as exc:
            raise DaemonError(
                f"Another daemon instance is already running ({exc})."
            ) from exc

        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def _release_pid_lock(self) -> None:
        """Release daemon PID metadata and repo runtime lock."""
        pid_path = self.repo_root / _PID_FILE
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        if self._runtime_guard is not None:
            self._runtime_guard.release()
            self._runtime_guard = None

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Persist daemon state atomically."""
        save_daemon_state(self.repo_root, self._state)

    def _persist_queue(self) -> None:
        """Persist queue state atomically."""
        queue_path = self.repo_root / ".colonyos" / "queue.json"
        archive_terminal_queue_items(self.repo_root, self._queue_state)
        atomic_write_json(queue_path, self._queue_state.to_dict())

    def _load_or_create_queue(self) -> QueueState:
        """Load existing queue state or create a fresh one."""
        queue_path = self.repo_root / ".colonyos" / "queue.json"
        if queue_path.exists():
            try:
                data = json.loads(queue_path.read_text(encoding="utf-8"))
                return QueueState.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt queue.json, starting fresh")
        return QueueState(queue_id=f"daemon-{int(time.time())}")

    def _pending_count(self) -> int:
        """Count pending items (user-sourced only, excludes CEO/cleanup)."""
        return sum(
            1
            for item in self._queue_state.items
            if item.status == QueueItemStatus.PENDING
            and item.source_type not in ("ceo", "cleanup")
        )

    def _is_duplicate(self, source_type: str, source_value: str) -> bool:
        """Check if an item with the same source already exists in a non-terminal state."""
        terminal = {QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.REJECTED}
        for item in self._queue_state.items:
            if (
                item.source_type == source_type
                and item.source_value == source_value
                and item.status not in terminal
            ):
                return True
        return False

    def get_health(self) -> dict[str, Any]:
        """Return health status for the /healthz endpoint."""
        with self._lock:
            allowed, remaining = self._state.check_daily_budget(self.daily_budget)
            cb_active = self._state.is_circuit_breaker_active()

            # Determine status
            if not allowed:
                status = "stopped"
            elif cb_active or self._state.paused:
                status = "degraded"
            else:
                status = "healthy"

            # Heartbeat age
            hb_age: float | None = None
            if self._state.last_heartbeat:
                try:
                    hb = datetime.fromisoformat(self._state.last_heartbeat)
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    hb_age = (datetime.now(timezone.utc) - hb).total_seconds()
                except (ValueError, TypeError):
                    pass

            pending = sum(
                1 for i in self._queue_state.items
                if i.status == QueueItemStatus.PENDING
            )

            # Pipeline duration and stall info
            running_item = self._current_running_item
            pipeline_started_at_iso: str | None = None
            pipeline_duration: float | None = None
            if running_item is not None and running_item.started_at is not None:
                pipeline_started_at_iso = running_item.started_at
            if self._pipeline_started_at is not None:
                pipeline_duration = time.monotonic() - self._pipeline_started_at

            return {
                "status": status,
                "heartbeat_age_seconds": hb_age,
                "queue_depth": pending,
                "daily_spend_usd": self._state.daily_spend_usd,
                "daily_budget_remaining_usd": remaining,
                "circuit_breaker_active": cb_active,
                "paused": self._state.paused,
                "pipeline_running": self._pipeline_running,
                "pipeline_started_at": pipeline_started_at_iso,
                "pipeline_duration_seconds": pipeline_duration,
                "pipeline_stalled": self._pipeline_stalled,
                "total_items_today": self._state.total_items_today,
                "consecutive_failures": self._state.consecutive_failures,
            }

    def _budget_cap_label(self) -> str:
        """Return a user-facing budget cap label."""
        if self.daily_budget is None:
            return "unlimited"
        return f"${self.daily_budget:.2f}/day"

    def _spent_summary(self, *, spend: float | None = None) -> str:
        """Return a spend summary string for logs and status output."""
        current_spend = self._state.daily_spend_usd if spend is None else spend
        if self.daily_budget is None:
            return f"${current_spend:.2f}/unlimited"
        return f"${current_spend:.2f}/${self.daily_budget:.2f}"

    def _record_runtime_incident(
        self,
        *,
        label_prefix: str,
        summary: str,
        metadata: dict[str, object],
    ) -> Path | None:
        """Write an actionable recovery incident summary for daemon failures."""
        try:
            from colonyos.recovery import incident_slug, write_incident_summary

            label = incident_slug(label_prefix)
            return write_incident_summary(
                self.repo_root,
                label,
                summary=summary,
                metadata=metadata,
            )
        except Exception:
            logger.exception("Failed to write daemon recovery incident")
            return None

    def _maybe_record_budget_incident(self, *, today: str, pending: int) -> Path | None:
        """Write at most one budget-exhaustion incident per UTC day."""
        if self._last_budget_incident_date == today:
            return None
        incident_path = self._record_runtime_incident(
            label_prefix="daemon-budget-exhausted",
            summary=(
                "The daemon stopped pulling new queue items because the daily budget was exhausted.\n\n"
                f"Spend: {self._spent_summary()}\n"
                f"Pending items: {pending}\n"
                "Wait for the next UTC day, raise daemon.daily_budget_usd, or restart with "
                "--unlimited-budget if this run should ignore the cap."
            ),
            metadata={
                "daily_spend_usd": self._state.daily_spend_usd,
                "daily_budget": self.daily_budget,
                "pending_items": pending,
            },
        )
        if incident_path is not None:
            self._last_budget_incident_date = today
        return incident_path

    def _budget_exhaustion_guidance(self, *, incident_path: Path | None) -> str:
        """Return actionable operator guidance for budget exhaustion."""
        guidance = (
            "Wait for the next UTC reset, increase daemon.daily_budget_usd, "
            "or restart with --unlimited-budget."
        )
        if incident_path is not None:
            return f"{guidance} Incident summary: {incident_path}"
        return guidance

    def _is_systemic_failure(self) -> bool:
        """True when all recent failure codes are identical (systemic issue)."""
        codes = self._recent_failure_codes
        if len(codes) < self.daemon_config.max_consecutive_failures:
            return False
        return len(set(codes)) == 1

    def _post_systemic_failure_alert(self, error_code: str, failures: int) -> None:
        """Post a Slack alert when the daemon auto-pauses due to systemic failures."""
        self._post_slack_message(
            f":rotating_light: *Daemon auto-paused (same error)*\n"
            f"{failures} consecutive failures with the same error: `{error_code}`\n"
            f"The daemon will not process any more items until manually resumed.\n"
            "Send `resume` in this channel to unpause."
        )

    def _post_circuit_breaker_cooldown_notice(
        self,
        consecutive_failures: int,
        activation_count: int,
        cooldown_until_iso: str,
    ) -> None:
        """Slack when the breaker trips into cooldown (not auto-pause)."""
        self._post_slack_message(
            f":electric_plug: *Circuit breaker cooldown*\n"
            f"After {consecutive_failures} consecutive failures, activation "
            f"#{activation_count}. Cooldown until `{cooldown_until_iso}` (ISO UTC). "
            f"Execution resumes automatically after that unless the daemon is paused."
        )

    def _post_circuit_breaker_escalation_pause_alert(
        self,
        activation_count: int,
        consecutive_failures: int,
    ) -> None:
        """Auto-pause after repeated breaker activations without a success (mixed errors)."""
        self._post_slack_message(
            f":rotating_light: *Daemon auto-paused (circuit breaker escalation)*\n"
            f"Breaker activation #{activation_count} without an intervening success "
            f"(last trip after {consecutive_failures} consecutive failures). "
            f"This is not the same-error systemic case.\n"
            "Send `resume` in this channel to unpause."
        )

    def _pause_for_pre_execution_blocker(self, item: QueueItem, reason: str) -> None:
        """Pause the daemon when pre-execution repo health blocks forward progress."""
        with self._lock:
            if self._state.paused or self._state.is_circuit_breaker_active():
                return
            self._state.paused = True
            self._state.circuit_breaker_until = None
            self._persist_state()

        incident_path = self._record_runtime_incident(
            label_prefix="daemon-preexec-blocked",
            summary=(
                f"{reason}\n\n"
                f"Pending item: {item.id}\n"
                f"Source type: {item.source_type}\n"
                f"Source value: {item.source_value[:500]}\n"
                "The daemon paused itself to avoid retrying the same blocked state indefinitely."
            ),
            metadata={
                "item_id": item.id,
                "source_type": item.source_type,
                "source_value": item.source_value[:500],
                "reason": reason,
            },
        )
        self._post_slack_message(
            ":rotating_light: *Daemon auto-paused before execution*\n"
            f"{reason}\n"
            f"Pending item: `{item.id}`\n"
            f"Incident summary: `{incident_path}`\n"
            "Fix the repo state, then send `resume` in Slack."
        )

    def _failure_summary(self, exc: Exception) -> str:
        """Return a concise failure summary for queue item state and logs."""
        text = str(exc).strip() or exc.__class__.__name__
        return text[:500]

    def _failure_guidance(self, exc: Exception) -> str:
        """Return actionable remediation guidance for common daemon failures."""
        text = self._failure_summary(exc).lower()
        if "credit balance is too low" in text:
            return (
                "Claude could not run because the active account has no credits. "
                "Top up credits, or unset ANTHROPIC_API_KEY if you meant to use a Claude subscription."
            )
        if "authentication failed" in text or "unauthorized" in text:
            return (
                "Check Claude authentication. Run `claude -p \"hello\"` in this repo and verify "
                "whether ANTHROPIC_API_KEY is set intentionally."
            )
        if "claude cli exited without details" in text or "exit code 1" in text:
            return (
                "Claude CLI exited without a useful error. Run `claude -p \"hello\"` manually, "
                "inspect local auth/env config, and review the incident summary for queue context."
            )
        if "temporarily overloaded" in text or "rate limited" in text or "overloaded" in text:
            return (
                "The Claude API is overloaded or rate limited. Retry later, reduce concurrency elsewhere, "
                "or configure retry fallback behavior if this keeps happening."
            )
        return (
            "Review the incident summary and daemon logs for full context, then rerun once the underlying "
            "repo or Claude CLI issue is fixed."
        )

    def _format_item_error(self, message: str, *, incident_path: Path | None) -> str:
        """Format a queue item error with an optional incident reference."""
        if incident_path is None:
            return message[:500]
        return f"{message[:350]} (incident: {incident_path})"[:500]
