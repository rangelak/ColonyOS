"""PostHog telemetry for ColonyOS.

Emits anonymized pipeline lifecycle events to PostHog when opted in.
All functions are silent no-ops when telemetry is disabled, the PostHog
SDK is not installed, or when any error occurs — analytics must never
block or slow the pipeline.

Environment variables
---------------------
- ``COLONYOS_POSTHOG_API_KEY`` — required to enable telemetry.
- ``COLONYOS_POSTHOG_HOST`` — optional custom PostHog instance URL.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import Any

from colonyos.config import PostHogConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Property allowlist — only these keys may be sent to PostHog.
# Everything else (prompts, branch names, error strings, artifact content,
# project names/descriptions, persona content) is explicitly blocked to
# protect user privacy.
# ---------------------------------------------------------------------------
_ALLOWED_PROPERTIES: frozenset[str] = frozenset({
    # run_started
    "model",
    "phase_config",
    "persona_count",
    "budget_per_run",
    "colonyos_version",
    # phase_completed
    "phase_name",
    "cost_usd",
    "duration_ms",
    "success",
    # run_completed
    "status",
    "total_cost_usd",
    "total_duration_ms",
    "phase_count",
    "fix_iteration_count",
    # run_failed
    "failing_phase_name",
    # cli_command
    "command_name",
})


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_posthog_client: Any = None
_enabled: bool = False
_distinct_id: str = ""


def _generate_anonymous_id(config_dir: Path) -> str:
    """Generate or load a stable anonymous installation ID.

    The ID is a SHA-256 hash of a random UUID, persisted in
    ``.colonyos/telemetry_id`` so it remains stable across runs
    but contains no personally identifiable information.
    """
    telemetry_id_path = config_dir / "telemetry_id"
    if telemetry_id_path.exists():
        stored = telemetry_id_path.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    # Generate from machine identifier + config dir path for stability,
    # but hash it to anonymize.
    raw = f"{platform.node()}:{config_dir}"
    anonymous_id = hashlib.sha256(raw.encode()).hexdigest()

    try:
        telemetry_id_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_id_path.write_text(anonymous_id + "\n", encoding="utf-8")
    except OSError:
        logger.debug("Failed to persist telemetry ID to %s", telemetry_id_path)

    return anonymous_id


def _filter_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Strip any properties not in the allowlist."""
    return {k: v for k, v in properties.items() if k in _ALLOWED_PROPERTIES}


def init_telemetry(config: PostHogConfig, config_dir: Path | None = None) -> None:
    """Initialize the telemetry subsystem.

    Reads the PostHog API key from ``COLONYOS_POSTHOG_API_KEY`` and
    optionally the host from ``COLONYOS_POSTHOG_HOST``.  If the SDK is
    not installed or the key is missing, telemetry silently remains
    disabled.
    """
    global _posthog_client, _enabled, _distinct_id  # noqa: PLW0603

    _enabled = False
    _posthog_client = None

    if not config.enabled:
        return

    api_key = os.environ.get("COLONYOS_POSTHOG_API_KEY", "").strip()
    if not api_key:
        logger.debug("PostHog telemetry enabled but COLONYOS_POSTHOG_API_KEY not set")
        return

    try:
        import posthog as posthog_sdk
    except ImportError:
        logger.debug(
            "PostHog telemetry enabled but posthog SDK not installed. "
            "Install with: pip install 'colonyos[posthog]'"
        )
        return

    host = os.environ.get("COLONYOS_POSTHOG_HOST", "").strip()
    if host:
        posthog_sdk.host = host
    posthog_sdk.project_api_key = api_key

    _posthog_client = posthog_sdk
    _enabled = True

    if config_dir is not None:
        _distinct_id = _generate_anonymous_id(config_dir)
    else:
        _distinct_id = hashlib.sha256(
            f"{platform.node()}:unknown".encode()
        ).hexdigest()

    logger.debug("PostHog telemetry initialized (distinct_id=%s...)", _distinct_id[:12])


def capture(event_name: str, properties: dict[str, Any] | None = None) -> None:
    """Send a telemetry event to PostHog.

    Silently no-ops if telemetry is disabled, the SDK is missing, or any
    error occurs.  Never raises.
    """
    if not _enabled or _posthog_client is None:
        return

    try:
        safe_props = _filter_properties(properties or {})
        _posthog_client.capture(
            distinct_id=_distinct_id,
            event=event_name,
            properties=safe_props,
        )
    except Exception:
        logger.debug("PostHog capture failed for event '%s'", event_name, exc_info=True)


def shutdown() -> None:
    """Flush the PostHog event queue and shut down.

    Called once at CLI exit.  Silently no-ops if telemetry is not active.
    """
    if not _enabled or _posthog_client is None:
        return

    try:
        _posthog_client.shutdown()
    except Exception:
        logger.debug("PostHog shutdown failed", exc_info=True)


# ---------------------------------------------------------------------------
# Convenience capture functions with typed signatures
# ---------------------------------------------------------------------------


def capture_run_started(
    *,
    model: str,
    phase_config: dict[str, bool],
    persona_count: int,
    budget_per_run: float,
    colonyos_version: str,
) -> None:
    """Capture a ``run_started`` event."""
    capture("run_started", {
        "model": model,
        "phase_config": phase_config,
        "persona_count": persona_count,
        "budget_per_run": budget_per_run,
        "colonyos_version": colonyos_version,
    })


def capture_phase_completed(
    *,
    phase_name: str,
    model: str,
    cost_usd: float,
    duration_ms: int,
    success: bool,
) -> None:
    """Capture a ``phase_completed`` event."""
    capture("phase_completed", {
        "phase_name": phase_name,
        "model": model,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "success": success,
    })


def capture_run_completed(
    *,
    status: str,
    total_cost_usd: float,
    total_duration_ms: int,
    phase_count: int,
    fix_iteration_count: int,
    colonyos_version: str,
) -> None:
    """Capture a ``run_completed`` event."""
    capture("run_completed", {
        "status": status,
        "total_cost_usd": total_cost_usd,
        "total_duration_ms": total_duration_ms,
        "phase_count": phase_count,
        "fix_iteration_count": fix_iteration_count,
        "colonyos_version": colonyos_version,
    })


def capture_run_failed(
    *,
    failing_phase_name: str,
    colonyos_version: str,
) -> None:
    """Capture a ``run_failed`` event."""
    capture("run_failed", {
        "failing_phase_name": failing_phase_name,
        "colonyos_version": colonyos_version,
    })


def capture_cli_command(
    *,
    command_name: str,
    colonyos_version: str,
) -> None:
    """Capture a ``cli_command`` event."""
    capture("cli_command", {
        "command_name": command_name,
        "colonyos_version": colonyos_version,
    })
