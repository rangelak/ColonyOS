"""Resilience mixin — crash recovery and dirty-worktree handling."""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Literal

from pathlib import Path

from colonyos.models import PreflightError, QueueItem, QueueItemStatus

logger = logging.getLogger(__name__)


class _ResilienceMixin:
    """Mixin providing crash-recovery and worktree-resilience methods for the Daemon class.

    All methods access Daemon state via ``self`` — they remain bound to the
    Daemon instance, so ``patch.object(daemon_instance, ...)`` targets are
    unchanged.

    Methods that use lazy imports (``from colonyos.recovery import ...``,
    ``from colonyos.orchestrator import ...``) keep those imports inside the
    method body to avoid circular import issues.
    """

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
