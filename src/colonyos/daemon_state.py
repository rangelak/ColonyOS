"""Daemon state persistence with atomic file writes.

Tracks daily spend, circuit breaker state, and daemon health for crash-safe
24/7 operation. State is persisted to ``.colonyos/daemon_state.json`` using
write-to-temp-then-rename to prevent corruption from mid-write crashes.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DaemonState:
    """Persistent state for the daemon process.

    Tracks daily spend (reset at midnight UTC), circuit breaker state,
    and operational counters. Serialized to JSON via ``to_dict`` /
    ``from_dict`` and persisted atomically via ``atomic_write_json``.
    """

    daily_spend_usd: float = 0.0
    daily_reset_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    consecutive_failures: int = 0
    circuit_breaker_until: str | None = None
    total_items_today: int = 0
    daemon_started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_heartbeat: str | None = None
    paused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_spend_usd": self.daily_spend_usd,
            "daily_reset_date": self.daily_reset_date,
            "consecutive_failures": self.consecutive_failures,
            "circuit_breaker_until": self.circuit_breaker_until,
            "total_items_today": self.total_items_today,
            "daemon_started_at": self.daemon_started_at,
            "last_heartbeat": self.last_heartbeat,
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DaemonState:
        return cls(
            daily_spend_usd=float(data.get("daily_spend_usd", 0.0)),
            daily_reset_date=data.get(
                "daily_reset_date",
                datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            ),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            circuit_breaker_until=data.get("circuit_breaker_until"),
            total_items_today=int(data.get("total_items_today", 0)),
            daemon_started_at=data.get(
                "daemon_started_at",
                datetime.now(timezone.utc).isoformat(),
            ),
            last_heartbeat=data.get("last_heartbeat"),
            paused=bool(data.get("paused", False)),
        )

    def check_daily_budget(self, cap: float | None) -> tuple[bool, float | None]:
        """Check if a new run is allowed under the daily budget.

        Returns (allowed, remaining_usd). Automatically resets counters
        if the UTC date has rolled over.
        """
        self._maybe_reset_daily()
        if cap is None:
            return True, None
        remaining = cap - self.daily_spend_usd
        return remaining > 0, max(remaining, 0.0)

    def record_spend(self, amount_usd: float) -> None:
        """Record spend from a completed pipeline run."""
        self._maybe_reset_daily()
        self.daily_spend_usd += amount_usd
        self.total_items_today += 1

    def record_failure(self) -> int:
        """Increment consecutive failure counter. Returns new count."""
        self.consecutive_failures += 1
        return self.consecutive_failures

    def record_success(self) -> None:
        """Reset consecutive failure counter on success."""
        self.consecutive_failures = 0
        self.circuit_breaker_until = None

    def activate_circuit_breaker(self, cooldown_minutes: int) -> str:
        """Set circuit breaker expiry. Returns the expiry ISO timestamp."""
        from datetime import timedelta

        expiry = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
        self.circuit_breaker_until = expiry.isoformat()
        return self.circuit_breaker_until

    def is_circuit_breaker_active(self) -> bool:
        """Return True if circuit breaker is still in cooldown."""
        if not self.circuit_breaker_until:
            return False
        try:
            expiry = datetime.fromisoformat(self.circuit_breaker_until)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) < expiry
        except (ValueError, TypeError):
            self.circuit_breaker_until = None
            return False

    def touch_heartbeat(self) -> None:
        """Update the heartbeat timestamp."""
        self.last_heartbeat = datetime.now(timezone.utc).isoformat()

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters if the UTC date has changed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_reset_date != today:
            self.daily_spend_usd = 0.0
            self.total_items_today = 0
            self.daily_reset_date = today


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON data to *path* atomically via write-then-rename.

    Creates a temporary file in the same directory, writes the JSON
    payload, then uses ``os.replace`` (atomic on POSIX) to swap it
    into place. This prevents corruption if the process is killed
    mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_daemon_state(repo_root: Path) -> DaemonState:
    """Load daemon state from ``.colonyos/daemon_state.json``.

    Returns a fresh ``DaemonState`` if the file does not exist or is
    corrupt.
    """
    state_path = repo_root / ".colonyos" / "daemon_state.json"
    if not state_path.exists():
        return DaemonState()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return DaemonState.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Corrupt daemon state file, starting fresh: %s", exc)
        return DaemonState()


def save_daemon_state(repo_root: Path, state: DaemonState) -> Path:
    """Persist daemon state atomically to ``.colonyos/daemon_state.json``."""
    state_path = repo_root / ".colonyos" / "daemon_state.json"
    atomic_write_json(state_path, state.to_dict())
    return state_path
