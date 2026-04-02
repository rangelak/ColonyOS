"""Watchdog mixin — detects and recovers stuck pipelines."""
from __future__ import annotations

import importlib
import logging
import sys
import time
import threading
from typing import TYPE_CHECKING, Any, Protocol, cast

from colonyos.tui.monitor_protocol import encode_monitor_event

if TYPE_CHECKING:
    from colonyos.models import QueueItemStatus

logger = logging.getLogger(__name__)


class _QueueItemStatusEnum(Protocol):
    FAILED: QueueItemStatus


class _DaemonModule(Protocol):
    QueueItemStatus: _QueueItemStatusEnum

    def active_phase_controller_count(self) -> int: ...

    def request_active_phase_cancel(self, reason: str = "Cancelled by user") -> int: ...

    def request_cancel(self, reason: str = "Cancelled by user") -> int: ...


def _host(obj: object) -> Any:
    return cast(Any, obj)


def _get_daemon_module() -> _DaemonModule:
    """Lazily fetch the colonyos.daemon package module.

    This avoids circular imports and ensures that ``patch("colonyos.daemon.X")``
    targets are honoured — the mixin looks up names from the same namespace that
    tests patch.
    """
    return cast(_DaemonModule, cast(object, importlib.import_module("colonyos.daemon")))


class WatchdogMixin:
    """Mixin providing watchdog thread management for the Daemon class.

    All methods access Daemon state via ``self`` — they remain bound to the
    Daemon instance, so ``patch.object(daemon_instance, ...)`` targets are
    unchanged.

    Functions that tests patch at ``colonyos.daemon.<name>`` are looked up from
    the daemon package namespace at call time so that ``unittest.mock.patch``
    substitutions take effect.
    """

    def _start_watchdog_thread(self) -> None:
        """Start the watchdog thread that detects stuck pipelines."""
        host = _host(self)
        t = threading.Thread(
            target=host._watchdog_loop,
            name="daemon-watchdog",
            daemon=True,
        )
        t.start()
        host._watchdog_thread = t

    def _watchdog_loop(self) -> None:
        """Main watchdog loop — wakes every 30s to check for stalled pipelines."""
        host = _host(self)
        while not host._stop_event.is_set():
            try:
                host._watchdog_check()
            except Exception:
                logger.exception("Watchdog check failed")
            host._stop_event.wait(30)

    def _watchdog_check(self) -> None:
        """Single watchdog check cycle. Detects stalls and triggers recovery."""
        host = _host(self)
        if not host._pipeline_running:
            return

        stall_seconds = host.daemon_config.watchdog_stall_seconds

        # Check 1: Has the pipeline been running longer than the threshold?
        pipeline_started = host._pipeline_started_at
        if pipeline_started is None:
            return
        elapsed = time.monotonic() - pipeline_started
        if elapsed < stall_seconds:
            return

        # Check 2: Is the heartbeat file stale?
        heartbeat_path = host.repo_root / ".colonyos" / "runs" / "heartbeat"
        try:
            hb_mtime = heartbeat_path.stat().st_mtime
            time_since_heartbeat = time.time() - hb_mtime
        except FileNotFoundError:
            # No heartbeat file = no progress signal at all
            time_since_heartbeat = elapsed

        if time_since_heartbeat < stall_seconds:
            return

        # Look up via the daemon module namespace so unittest.mock.patch
        # targets (e.g. "colonyos.daemon.active_phase_controller_count") work.
        mod = _get_daemon_module()
        active_phases = mod.active_phase_controller_count()
        if active_phases > 0:
            logger.info(
                "Watchdog: suppressing stall recovery for active pipeline "
                "(elapsed=%.0fs, threshold=%ds, heartbeat_age=%.0fs, active_phases=%d)",
                elapsed,
                stall_seconds,
                time_since_heartbeat,
                active_phases,
            )
            return

        # Both conditions met: pipeline is stalled
        host._pipeline_stalled = True
        logger.warning(
            "Watchdog: pipeline stalled for %.0fs "
            "(threshold=%ds, heartbeat_age=%.0fs, active_phases=%d)",
            elapsed,
            stall_seconds,
            time_since_heartbeat,
            active_phases,
        )
        host._watchdog_recover(stall_duration=elapsed)

    def _watchdog_recover(self, stall_duration: float) -> None:
        """Recover from a stalled pipeline: cancel, wait, force-reset, mark FAILED."""
        # Lazy module lookup: these functions are patched at "colonyos.daemon.<name>"
        # in tests, so we must call them via the module namespace, not direct import.
        host = _host(self)
        mod = _get_daemon_module()
        item = host._current_running_item

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
            host._post_slack_message(alert_msg)
        except Exception:
            logger.exception("Watchdog: failed to post Slack alert")

        # Step 1: Request graceful phase cancellation
        logger.warning("Watchdog: requesting active phase cancel")
        try:
            mod.request_active_phase_cancel(
                f"watchdog: no progress for {stall_duration:.0f}s"
            )
        except Exception:
            logger.exception("Watchdog: request_active_phase_cancel failed")

        # Step 2: Grace period — wait 30s for cooperative cancellation
        host._stop_event.wait(30)

        # Step 3: If still stuck, force cancel
        if host._pipeline_running:
            logger.warning("Watchdog: pipeline still running after grace period, forcing cancel")
            try:
                mod.request_cancel(
                    f"watchdog: forced fallback cancellation after grace period ({stall_duration:.0f}s stall)"
                )
            except Exception:
                logger.exception("Watchdog: request_cancel fallback failed")

        # Step 4: Force-reset state under lock
        with host._lock:
            host._pipeline_running = False
            host._pipeline_started_at = None
            host._current_running_item = None
            if item is not None:
                item.status = mod.QueueItemStatus.FAILED
                item.error = f"watchdog: no progress for {stall_duration:.0f}s"
            host._persist_queue()
