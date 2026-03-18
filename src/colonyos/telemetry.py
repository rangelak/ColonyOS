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

import logging
import os
import tempfile
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
# NOTE: not thread-safe. ColonyOS is single-threaded; if concurrency is
# added in the future, guard these globals with a threading.Lock.
# ---------------------------------------------------------------------------
_posthog_client: Any = None
_enabled: bool = False
_distinct_id: str = ""


def _generate_anonymous_id(config_dir: Path) -> str:
    """Generate or load a stable anonymous installation ID.

    The ID is a random UUID persisted in ``.colonyos/telemetry_id`` so it
    remains stable across runs but contains no personally identifiable
    information.  Uses atomic write (temp file + rename) to avoid TOCTOU
    races when concurrent processes first create the file.
    """
    telemetry_id_path = config_dir / "telemetry_id"
    if telemetry_id_path.exists():
        stored = telemetry_id_path.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    # Generate a fully random UUID — no machine identifiers involved.
    anonymous_id = str(uuid.uuid4())

    try:
        telemetry_id_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file then rename to avoid races.
        fd, tmp = tempfile.mkstemp(
            dir=str(telemetry_id_path.parent), prefix=".telemetry_id_"
        )
        closed = False
        try:
            os.write(fd, (anonymous_id + "\n").encode())
            os.close(fd)
            closed = True
            os.rename(tmp, str(telemetry_id_path))
        except BaseException:
            if not closed:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        logger.debug("Failed to persist telemetry ID to %s", telemetry_id_path)

    return anonymous_id


def _filter_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Strip any properties not in the allowlist."""
    return {k: v for k, v in properties.items() if k in _ALLOWED_PROPERTIES}


def is_initialized() -> bool:
    """Return True if telemetry has already been initialized."""
    return _enabled


def init_telemetry(config: PostHogConfig, config_dir: Path | None = None) -> None:
    """Initialize the telemetry subsystem.

    Reads the PostHog API key from ``COLONYOS_POSTHOG_API_KEY`` and
    optionally the host from ``COLONYOS_POSTHOG_HOST``.  If the SDK is
    not installed or the key is missing, telemetry silently remains
    disabled.

    If telemetry is already initialized, this function is a no-op to
    avoid overwriting state (e.g. ``_distinct_id``) mid-run.
    """
    global _posthog_client, _enabled, _distinct_id  # noqa: PLW0603

    # Guard: don't re-initialize if already active.
    if _enabled:
        return

    _enabled = False
    _posthog_client = None

    if not config.enabled:
        return

    api_key = os.environ.get("COLONYOS_POSTHOG_API_KEY", "").strip()
    if not api_key:
        logger.debug("PostHog telemetry enabled but COLONYOS_POSTHOG_API_KEY not set")
        return

    try:
        from posthog import Posthog
    except ImportError:
        logger.debug(
            "PostHog telemetry enabled but posthog SDK not installed. "
            "Install with: pip install 'colonyos[posthog]'"
        )
        return

    host = os.environ.get("COLONYOS_POSTHOG_HOST", "").strip() or "https://us.i.posthog.com"

    # Use an isolated Client instance rather than mutating the posthog
    # module's global state, to avoid leaking config to/from other code
    # that may import posthog.
    _posthog_client = Posthog(api_key, host=host)
    _enabled = True

    if config_dir is not None:
        _distinct_id = _generate_anonymous_id(config_dir)
    else:
        _distinct_id = str(uuid.uuid4())

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

    Idempotent: subsequent calls after the first are silent no-ops,
    so it is safe to call from both ``atexit`` handlers and explicit
    orchestrator exit paths.
    """
    global _enabled  # noqa: PLW0603

    if not _enabled or _posthog_client is None:
        return

    # Mark as disabled *before* calling SDK shutdown so that a second
    # call (e.g. from atexit) is a no-op.
    _enabled = False

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
