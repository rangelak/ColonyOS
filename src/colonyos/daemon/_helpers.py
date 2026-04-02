"""Helper and formatting methods for the Daemon class.

Pure-ish functions that read ``self.*`` state but don't mutate it
(except ``_record_runtime_incident`` which writes files).
Extracted as a mixin so methods remain on ``self`` and
``patch.object`` mock targets are unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colonyos.config import ColonyConfig

logger = logging.getLogger(__name__)


class _HelpersMixin:
    """Mixin providing helper/formatting methods for Daemon."""

    @staticmethod
    def _warn_all_mode_safety(config: ColonyConfig) -> None:
        """Log warnings when trigger_mode is 'all' without safety configs."""
        if config.slack.trigger_mode != "all":
            return
        if not config.slack.allowed_user_ids:
            logger.warning(
                "trigger_mode is 'all' but allowed_user_ids is empty — "
                "any user in the channel can trigger the bot. "
                "Consider restricting allowed_user_ids."
            )
        if not config.slack.triage_scope:
            logger.warning(
                "trigger_mode is 'all' but triage_scope is empty — "
                "triage may struggle to filter irrelevant messages. "
                "Consider setting triage_scope to guide the triage LLM."
            )

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
