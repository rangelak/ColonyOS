"""ColonyOS Daemon — fully autonomous 24/7 engineering agent.

Unifies Slack listening, GitHub Issue polling, CEO idle-fill scheduling,
cleanup scheduling, and priority queue execution into a single supervised
long-running process.  Designed for systemd deployment on a VM.

Architecture:
    Single process, multiple threads.  One pipeline runs at a time
    (sequential execution).  Shared state protected by ``threading.Lock``.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from colonyos.config import ColonyConfig, load_config
from colonyos.daemon_state import (
    DaemonState,
    atomic_write_json,
    load_daemon_state,
    save_daemon_state,
)
from colonyos.models import (
    PRIORITY_CEO,
    PRIORITY_CLEANUP,
    QueueItem,
    QueueItemStatus,
    QueueState,
    QueueStatus,
    compute_priority,
)

logger = logging.getLogger(__name__)

# Sentinel file used as a single-instance lock
_PID_FILE = ".colonyos/daemon.pid"

# How often the main loop checks for work (seconds)
_MAIN_LOOP_INTERVAL = 5


class DaemonError(RuntimeError):
    """Raised for unrecoverable daemon errors."""


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

        # CLI overrides
        self.daily_budget = (
            None
            if unlimited_budget
            else max_budget if max_budget is not None else self.daemon_config.daily_budget_usd
        )
        self.max_hours = max_hours

        # Shared mutable state — protected by _lock
        self._lock = threading.Lock()
        self._state = load_daemon_state(repo_root)
        self._queue_state = self._load_or_create_queue()
        self._pipeline_running = False

        # Shutdown coordination
        self._stop_event = threading.Event()
        self._started_at = time.monotonic()

        # Track last schedule times
        self._last_ceo_time: float = 0.0
        self._last_cleanup_time: float = 0.0
        self._last_heartbeat_time: float = 0.0
        self._last_github_poll_time: float = 0.0

        # PID lock file descriptor
        self._pid_fd: int | None = None

        # Budget alert flags (reset on daily budget reset)
        self._budget_80_alerted: bool = False
        self._budget_100_alerted: bool = False

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

        # 1. Try to execute next queue item
        if not self._pipeline_running:
            self._try_execute_next()

        # 2. GitHub polling
        poll_interval = self.daemon_config.github_poll_interval_seconds
        if now - self._last_github_poll_time >= poll_interval:
            self._poll_github_issues()
            self._last_github_poll_time = now

        # 3. CEO idle-fill (only when queue is empty and no pipeline running)
        ceo_cooldown = self.daemon_config.ceo_cooldown_minutes * 60
        if (
            not self._pipeline_running
            and self._pending_count() == 0
            and now - self._last_ceo_time >= ceo_cooldown
        ):
            self._schedule_ceo()
            self._last_ceo_time = now

        # 4. Cleanup scheduling
        cleanup_interval = self.daemon_config.cleanup_interval_hours * 3600
        if now - self._last_cleanup_time >= cleanup_interval:
            self._schedule_cleanup()
            self._last_cleanup_time = now

        # 5. Heartbeat
        heartbeat_interval = self.daemon_config.heartbeat_interval_minutes * 60
        if now - self._last_heartbeat_time >= heartbeat_interval:
            self._post_heartbeat()
            self._last_heartbeat_time = now

    # ------------------------------------------------------------------
    # Queue execution
    # ------------------------------------------------------------------

    def _try_execute_next(self) -> None:
        """Pop the highest-priority pending item and execute it."""
        with self._lock:
            if self._state.paused:
                return

            # Budget check (reset alert flags if daily counters were reset)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._state.daily_reset_date != today:
                self._budget_80_alerted = False
                self._budget_100_alerted = False

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
                logger.warning(
                    "Daily budget exhausted; queue remains idle (spent=$%.2f, cap=%s, pending=%d)",
                    self._state.daily_spend_usd,
                    self._budget_cap_label(),
                    sum(
                        1
                        for queued_item in self._queue_state.items
                        if queued_item.status == QueueItemStatus.PENDING
                    ),
                )
                return

            # Circuit breaker check
            if self._state.is_circuit_breaker_active():
                logger.debug("Circuit breaker active, skipping execution")
                return

            # Find highest-priority pending item
            item = self._next_pending_item()
            if item is None:
                return

            item.status = QueueItemStatus.RUNNING
            self._pipeline_running = True
            self._persist_queue()

        # Execute outside the lock
        try:
            cost = self._execute_item(item)
            with self._lock:
                item.status = QueueItemStatus.COMPLETED
                item.cost_usd = cost
                self._state.record_spend(cost)
                self._state.record_success()
                self._pipeline_running = False
                self._persist_state()
                self._persist_queue()
                logger.info(
                    "Completed item %s (cost=$%.4f, spend=%s, pending=%d)",
                    item.id,
                    cost,
                    self._spent_summary(),
                    sum(
                        1
                        for queued_item in self._queue_state.items
                        if queued_item.status == QueueItemStatus.PENDING
                    ),
                )
        except KeyboardInterrupt:
            logger.warning("Run interrupted while executing item %s", item.id)
            with self._lock:
                item.status = QueueItemStatus.FAILED
                item.error = "Run interrupted by user (Ctrl+C)"
                self._pipeline_running = False
                self._persist_state()
                self._persist_queue()
            raise
        except Exception as exc:
            logger.exception("Pipeline failed for item %s", item.id)
            with self._lock:
                item.status = QueueItemStatus.FAILED
                item.error = str(exc)[:500]
                failures = self._state.record_failure()
                if failures >= self.daemon_config.max_consecutive_failures:
                    self._state.activate_circuit_breaker(
                        self.daemon_config.circuit_breaker_cooldown_minutes
                    )
                    logger.warning(
                        "Circuit breaker activated after %d consecutive failures",
                        failures,
                    )
                self._pipeline_running = False
                self._persist_state()
                self._persist_queue()

    def _next_pending_item(self) -> QueueItem | None:
        """Return the highest-priority pending item (lowest priority number, FIFO within tier).

        Also applies starvation promotion: items pending >24h get promoted one tier.
        """
        now = datetime.now(timezone.utc)
        pending = [
            item
            for item in self._queue_state.items
            if item.status == QueueItemStatus.PENDING
        ]
        if not pending:
            return None

        # Starvation promotion: items older than 24h get promoted one tier
        promoted = False
        for item in pending:
            try:
                added = datetime.fromisoformat(item.added_at)
                if added.tzinfo is None:
                    added = added.replace(tzinfo=timezone.utc)
                if (now - added).total_seconds() > 86400 and item.priority > 0:
                    item.priority -= 1
                    promoted = True
                    logger.info(
                        "Promoted item %s to priority %d (starvation prevention)",
                        item.id,
                        item.priority,
                    )
            except (ValueError, TypeError):
                pass

        if promoted:
            self._persist_queue()

        # Sort by priority (ascending), then by added_at (ascending = FIFO)
        pending.sort(key=lambda i: (i.priority, i.added_at))
        return pending[0]

    def _execute_item(self, item: QueueItem) -> float:
        """Execute a single queue item through the pipeline.

        Returns the cost in USD.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would execute item %s: %s", item.id, item.source_value[:100])
            return 0.0

        logger.info(
            "Executing item %s (type=%s, priority=%d)",
            item.id,
            item.source_type,
            item.priority,
        )

        # Import here to avoid circular imports — cli.py imports from many modules
        from colonyos.cli import run_pipeline_for_queue_item

        return run_pipeline_for_queue_item(
            item=item,
            repo_root=self.repo_root,
            config=self.config,
            verbose=self.verbose,
        )

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

                priority = compute_priority("issue", issue.labels)
                item = QueueItem(
                    id=f"issue-{issue.number}-{int(time.time())}",
                    source_type="issue",
                    source_value=str(issue.number),
                    status=QueueItemStatus.PENDING,
                    priority=priority,
                    issue_title=sanitize_untrusted_content(issue.title),
                )

                with self._lock:
                    self._queue_state.items.append(item)
                    self._persist_queue()

                logger.info(
                    "Enqueued GitHub issue #%d (P%d): %s",
                    issue.number,
                    priority,
                    issue.title,
                )

        except Exception:
            logger.exception("Error polling GitHub issues")

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
            from colonyos.ui import PhaseUI

            proposal_prompt, phase_result = run_ceo(
                repo_root=self.repo_root,
                config=self.config,
                ui=PhaseUI(verbose=self.verbose, prefix="CEO "),
            )

            if not phase_result.success:
                logger.warning(
                    "CEO idle-fill failed: %s",
                    phase_result.error or "unknown CEO error",
                )
                return

            if proposal_prompt:
                item = QueueItem(
                    id=f"ceo-{int(time.time())}",
                    source_type="ceo",
                    source_value=proposal_prompt,
                    status=QueueItemStatus.PENDING,
                    priority=PRIORITY_CEO,
                )
                with self._lock:
                    self._queue_state.items.append(item)
                    self._persist_queue()
                logger.info("CEO proposed work enqueued (P%d): %s", PRIORITY_CEO, proposal_prompt[:120])
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
                    priority=PRIORITY_CLEANUP,
                )
                with self._lock:
                    self._queue_state.items.append(item)
                    enqueued += 1

            if enqueued:
                with self._lock:
                    self._persist_queue()
                logger.info("Enqueued %d cleanup items", enqueued)

        except Exception:
            logger.exception("Error in cleanup scheduling")

    # ------------------------------------------------------------------
    # Health & Observability (FR-10)
    # ------------------------------------------------------------------

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
                preserve_and_reset_worktree(self.repo_root, "daemon_crash_recovery")
        except Exception:
            logger.exception("Error during git state recovery")

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

        return threads

    def _slack_listener_thread(self) -> None:
        """Run Slack Socket Mode listener."""
        try:
            from colonyos.slack import create_slack_app, start_socket_mode

            slack_app = create_slack_app(self.config.slack)
            self._register_daemon_commands(slack_app)
            logger.info("Slack listener thread started")
            start_socket_mode(slack_app)
        except Exception:
            logger.exception("Slack listener thread failed")

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
            self.stop()
            if self._pipeline_running:
                logger.warning("Interrupting active pipeline due to %s", sig_name)
                raise KeyboardInterrupt(f"{sig_name} received")

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    # ------------------------------------------------------------------
    # PID lock (FR — prevent multiple instances)
    # ------------------------------------------------------------------

    def _acquire_pid_lock(self) -> None:
        """Acquire PID lock file to prevent multiple daemon instances."""
        pid_path = self.repo_root / _PID_FILE
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._pid_fd = os.open(str(pid_path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self._pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(self._pid_fd, f"{os.getpid()}\n".encode())
            os.ftruncate(self._pid_fd, len(f"{os.getpid()}\n"))
        except OSError:
            if self._pid_fd is not None:
                os.close(self._pid_fd)
                self._pid_fd = None
            raise DaemonError(
                f"Another daemon instance is already running (lock file: {pid_path}). "
                "Stop the existing instance first or remove the lock file."
            )

    def _release_pid_lock(self) -> None:
        """Release PID lock file."""
        if self._pid_fd is not None:
            try:
                fcntl.flock(self._pid_fd, fcntl.LOCK_UN)
                os.close(self._pid_fd)
            except OSError:
                pass
            self._pid_fd = None

        pid_path = self.repo_root / _PID_FILE
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Persist daemon state atomically."""
        save_daemon_state(self.repo_root, self._state)

    def _persist_queue(self) -> None:
        """Persist queue state atomically."""
        queue_path = self.repo_root / ".colonyos" / "queue.json"
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

            return {
                "status": status,
                "heartbeat_age_seconds": hb_age,
                "queue_depth": pending,
                "daily_spend_usd": self._state.daily_spend_usd,
                "daily_budget_remaining_usd": remaining,
                "circuit_breaker_active": cb_active,
                "paused": self._state.paused,
                "pipeline_running": self._pipeline_running,
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
