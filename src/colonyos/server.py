"""FastAPI application serving the ColonyOS web dashboard API.

Endpoints include read-only GET routes and optional write routes (PUT/POST)
gated behind ``COLONYOS_WRITE_ENABLED`` env var and bearer token auth.
The server wraps existing data-layer functions from ``stats.py``,
``show.py``, and ``config.py`` and serves pre-built Vite SPA assets
from ``web_dist/``.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path, save_config
from colonyos.models import Persona
from colonyos.runtime_lock import RepoRuntimeGuard, RuntimeBusyError
from colonyos.sanitize import sanitize_untrusted_content
from colonyos.show import (
    compute_show_result,
    resolve_run_id,
    validate_run_id_input,
)
from colonyos.stats import compute_stats, load_run_logs

logger = logging.getLogger(__name__)

# Path to the built Vite SPA assets (committed to repo)
_WEB_DIST_DIR = Path(__file__).parent / "web_dist"

# Fields that may contain secrets and must be redacted from config API output.
# Also blocks write attempts via API.
_SENSITIVE_CONFIG_FIELDS = {"slack", "ceo_persona"}

# Allowed artifact directory prefixes for the GET /api/artifacts endpoint.
_ALLOWED_ARTIFACT_DIRS = {"cOS_prds", "cOS_tasks", "cOS_reviews", "cOS_proposals"}


def _sanitize_run_log(log: dict[str, Any]) -> dict[str, Any]:
    """Sanitize user-generated content in a run log dict."""
    sanitized = dict(log)
    if "prompt" in sanitized and isinstance(sanitized["prompt"], str):
        sanitized["prompt"] = sanitize_untrusted_content(sanitized["prompt"])
    if "error" in sanitized and isinstance(sanitized["error"], str):
        sanitized["error"] = sanitize_untrusted_content(sanitized["error"])
    return sanitized


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Serialize a ColonyConfig to a JSON-safe dict, redacting sensitive fields."""
    raw = asdict(config)
    for field_name in _SENSITIVE_CONFIG_FIELDS:
        raw.pop(field_name, None)
    return raw


def create_app(repo_root: Path) -> tuple[FastAPI, str]:
    """Create and configure the FastAPI application.

    Args:
        repo_root: Path to the repository root containing ``.colonyos/``.

    Returns:
        A tuple of (FastAPI app, bearer token for write endpoints).
    """
    app = FastAPI(
        title="ColonyOS Dashboard",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )

    # Generate auth token for write endpoints
    auth_token = secrets.token_urlsafe(32)
    write_enabled = bool(os.environ.get("COLONYOS_WRITE_ENABLED"))

    # Semaphore for rate limiting: max 1 concurrent run
    active_run_semaphore = threading.Semaphore(1)

    # CORS for local dev only (Vite dev server on a different port)
    if os.environ.get("COLONYOS_DEV"):
        allowed_methods = ["GET", "PUT", "POST"] if write_enabled else ["GET"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=allowed_methods,
            allow_headers=["Content-Type", "Accept", "Authorization"],
        )

    runs_dir = runs_dir_path(repo_root)

    def _require_write_auth(request: Request) -> None:
        """Validate write mode is enabled and bearer token is correct."""
        if not write_enabled:
            raise HTTPException(
                status_code=403,
                detail="Write mode is not enabled. Set COLONYOS_WRITE_ENABLED=1.",
            )
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        provided_token = auth_header[7:]
        if not secrets.compare_digest(provided_token, auth_token):
            raise HTTPException(status_code=401, detail="Invalid bearer token")

    # -----------------------------------------------------------------------
    # Read endpoints (no auth required)
    # -----------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "write_enabled": str(write_enabled).lower()}

    # Live daemon reference — set by Daemon.start() when running in daemon mode
    app.state.daemon_instance = None

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Daemon health check endpoint (FR-10).

        Uses the live daemon instance's in-memory state when available,
        falling back to reading from disk for standalone server mode.
        """
        daemon = app.state.daemon_instance
        if daemon is not None:
            body = daemon.get_health()
            http_status = 200 if body["status"] == "healthy" else 503
            return JSONResponse(content=body, status_code=http_status)

        # Fallback: read from disk (standalone server, no live daemon)
        from colonyos.daemon_state import load_daemon_state

        config = load_config(repo_root)
        state = load_daemon_state(repo_root)
        state._maybe_reset_daily()

        daily_cap = config.daemon.daily_budget_usd
        allowed, remaining = state.check_daily_budget(daily_cap)
        cb_active = state.is_circuit_breaker_active()

        if not allowed:
            status = "stopped"
        elif cb_active or state.paused:
            status = "degraded"
        else:
            status = "healthy"

        heartbeat_age: float | None = None
        if state.last_heartbeat:
            try:
                hb = datetime.fromisoformat(state.last_heartbeat)
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                heartbeat_age = (datetime.now(timezone.utc) - hb).total_seconds()
            except (ValueError, TypeError):
                pass

        queue_path = repo_root / ".colonyos" / "queue.json"
        queue_depth = 0
        if queue_path.exists():
            try:
                q_data = json.loads(queue_path.read_text(encoding="utf-8"))
                queue_depth = sum(
                    1 for i in q_data.get("items", [])
                    if i.get("status") == "pending"
                )
            except (json.JSONDecodeError, KeyError):
                pass

        body = {
            "status": status,
            "heartbeat_age_seconds": heartbeat_age,
            "queue_depth": queue_depth,
            "daily_spend_usd": state.daily_spend_usd,
            "daily_budget_remaining_usd": remaining,
            "circuit_breaker_active": cb_active,
            "paused": state.paused,
            "total_items_today": state.total_items_today,
            "consecutive_failures": state.consecutive_failures,
        }

        http_status = 200 if status == "healthy" else 503
        return JSONResponse(content=body, status_code=http_status)

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        logs = load_run_logs(runs_dir)
        return [_sanitize_run_log(log) for log in logs]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            validate_run_id_input(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        try:
            resolved = resolve_run_id(runs_dir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        if isinstance(resolved, list):
            raise HTTPException(
                status_code=400,
                detail=f"Ambiguous run ID: matches multiple runs",
            )

        from colonyos.show import load_single_run

        try:
            run_data = load_single_run(runs_dir, resolved)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        show_result = compute_show_result(run_data)
        return asdict(show_result)

    @app.get("/api/stats")
    def get_stats() -> dict[str, Any]:
        logs = load_run_logs(runs_dir)
        result = compute_stats(logs)
        return asdict(result)

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        config = load_config(repo_root)
        return _config_to_dict(config)

    @app.get("/api/queue")
    def get_queue() -> dict[str, Any] | None:
        queue_path = repo_root / ".colonyos" / "queue.json"
        if not queue_path.exists():
            return None
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
            from colonyos.models import QueueState

            qs = QueueState.from_dict(data)
            return qs.to_dict()
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Failed to load queue state: %s", exc)
            return None

    # -----------------------------------------------------------------------
    # Write endpoints (auth required, gated by COLONYOS_WRITE_ENABLED)
    # -----------------------------------------------------------------------

    @app.put("/api/config")
    async def update_config(request: Request) -> dict[str, Any]:
        """Update configuration. Rejects mutations to sensitive fields."""
        _require_write_auth(request)

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")

        # Block sensitive field mutations
        for field_name in _SENSITIVE_CONFIG_FIELDS:
            if field_name in body:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field_name}' is not allowed to be modified via API",
                )

        config = load_config(repo_root)

        # Apply updates to non-sensitive fields
        if "model" in body:
            model = sanitize_untrusted_content(str(body["model"]))
            from colonyos.config import VALID_MODELS
            if model not in VALID_MODELS:
                raise HTTPException(status_code=400, detail=f"Invalid model: {model}")
            config.model = model

        if "budget" in body and isinstance(body["budget"], dict):
            budget = body["budget"]
            if "per_phase" in budget:
                config.budget.per_phase = float(budget["per_phase"])
            if "per_run" in budget:
                config.budget.per_run = float(budget["per_run"])
            if "max_duration_hours" in budget:
                config.budget.max_duration_hours = float(budget["max_duration_hours"])
            if "max_total_usd" in budget:
                config.budget.max_total_usd = float(budget["max_total_usd"])

        if "phases" in body and isinstance(body["phases"], dict):
            phases = body["phases"]
            if "plan" in phases:
                config.phases.plan = bool(phases["plan"])
            if "implement" in phases:
                config.phases.implement = bool(phases["implement"])
            if "review" in phases:
                config.phases.review = bool(phases["review"])
            if "deliver" in phases:
                config.phases.deliver = bool(phases["deliver"])

        if "project" in body and isinstance(body["project"], dict):
            from colonyos.models import ProjectInfo
            proj = body["project"]
            config.project = ProjectInfo(
                name=sanitize_untrusted_content(str(proj.get("name", ""))),
                description=sanitize_untrusted_content(str(proj.get("description", ""))),
                stack=sanitize_untrusted_content(str(proj.get("stack", ""))),
            )

        if "max_fix_iterations" in body:
            config.max_fix_iterations = int(body["max_fix_iterations"])

        if "auto_approve" in body:
            config.auto_approve = bool(body["auto_approve"])

        if "phase_models" in body and isinstance(body["phase_models"], dict):
            from colonyos.config import VALID_MODELS
            for phase, model in body["phase_models"].items():
                model_str = sanitize_untrusted_content(str(model))
                if model_str not in VALID_MODELS:
                    raise HTTPException(status_code=400, detail=f"Invalid model for {phase}: {model_str}")
            config.phase_models = {str(k): str(v) for k, v in body["phase_models"].items()}

        save_config(repo_root, config)
        return _config_to_dict(config)

    @app.put("/api/config/personas")
    async def update_personas(request: Request) -> dict[str, Any]:
        """Update the personas list. Validates each persona."""
        _require_write_auth(request)

        body = await request.json()
        if not isinstance(body, list):
            raise HTTPException(status_code=400, detail="Request body must be a JSON array of personas")

        personas = []
        for i, p in enumerate(body):
            if not isinstance(p, dict):
                raise HTTPException(status_code=400, detail=f"Persona at index {i} must be an object")
            role = p.get("role")
            expertise = p.get("expertise")
            perspective = p.get("perspective")
            if not role or not expertise or not perspective:
                raise HTTPException(
                    status_code=400,
                    detail=f"Persona at index {i} requires role, expertise, and perspective",
                )
            personas.append(Persona(
                role=sanitize_untrusted_content(str(role)),
                expertise=sanitize_untrusted_content(str(expertise)),
                perspective=sanitize_untrusted_content(str(perspective)),
                reviewer=bool(p.get("reviewer", False)),
            ))

        config = load_config(repo_root)
        # ColonyConfig.personas is a list; Persona is frozen so we replace the list
        config.personas = personas
        save_config(repo_root, config)
        return _config_to_dict(config)

    @app.get("/api/auth/verify")
    def verify_auth(request: Request) -> dict[str, str]:
        """Verify a bearer token is valid. Returns 401 if invalid."""
        _require_write_auth(request)
        return {"status": "ok"}

    @app.post("/api/runs")
    async def launch_run(request: Request) -> dict[str, Any]:
        """Launch an agent run in a background thread.

        Returns a status indicator. The orchestrator assigns the actual
        ``run_id`` asynchronously — poll GET /api/runs to discover new runs.
        """
        _require_write_auth(request)

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")

        prompt = body.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt is required and must be non-empty")

        # Do NOT sanitize the prompt here — sanitization should happen at
        # display time (in _sanitize_run_log), not at execution time, to
        # avoid silently altering user intent.

        # Rate limit: max 1 concurrent run via semaphore
        acquired = active_run_semaphore.acquire(blocking=False)
        if not acquired:
            raise HTTPException(status_code=429, detail="A run is already in progress")

        try:
            runtime_guard = RepoRuntimeGuard(repo_root, "ui-run").acquire()
        except RuntimeBusyError as exc:
            active_run_semaphore.release()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        def _run_in_background():
            try:
                from colonyos.orchestrator import run as run_orchestrator
                config = load_config(repo_root)
                run_orchestrator(
                    prompt,
                    repo_root=repo_root,
                    config=config,
                    quiet=True,
                )
            except Exception:
                logger.exception("Background run failed")
            finally:
                runtime_guard.release()
                active_run_semaphore.release()

        try:
            thread = threading.Thread(target=_run_in_background, daemon=True)
            thread.start()
        except Exception:
            # Release semaphore if thread creation/start fails
            runtime_guard.release()
            active_run_semaphore.release()
            raise HTTPException(status_code=500, detail="Failed to start background run")

        return {"status": "launched"}

    @app.get("/api/artifacts/{path:path}")
    def get_artifact(path: str) -> dict[str, Any]:
        """Serve content of artifact files from allowed directories."""
        # Validate path starts with an allowed directory
        path_parts = Path(path).parts
        if not path_parts:
            raise HTTPException(status_code=400, detail="Empty artifact path")

        top_dir = path_parts[0]
        if top_dir not in _ALLOWED_ARTIFACT_DIRS:
            raise HTTPException(
                status_code=400,
                detail=f"Access to directory '{top_dir}' is not allowed",
            )

        # Defense-in-depth: resolve and verify path stays within repo root
        file_path = (repo_root / path).resolve()
        resolved_root = repo_root.resolve()
        if not file_path.is_relative_to(resolved_root):
            raise HTTPException(status_code=400, detail="Path traversal detected")

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact not found")

        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        content = file_path.read_text(encoding="utf-8")
        return {
            "path": path,
            "content": sanitize_untrusted_content(content),
            "filename": file_path.name,
        }

    @app.get("/api/proposals")
    def list_proposals() -> list[dict[str, Any]]:
        """List all files in the proposals directory."""
        proposals_dir = repo_root / "cOS_proposals"
        if not proposals_dir.exists():
            return []
        files = sorted(proposals_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "filename": f.name,
                "path": f"cOS_proposals/{f.name}",
                "modified_at": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            for f in files
        ]

    @app.get("/api/reviews")
    def list_reviews() -> list[dict[str, Any]]:
        """List all review files organized by subdirectory."""
        reviews_dir = repo_root / "cOS_reviews"
        if not reviews_dir.exists():
            return []
        results = []
        for md_file in sorted(reviews_dir.rglob("*.md"), reverse=True):
            rel = md_file.relative_to(repo_root)
            results.append({
                "filename": md_file.name,
                "path": str(rel),
                "subdirectory": str(md_file.parent.relative_to(reviews_dir)),
                "modified_at": datetime.fromtimestamp(
                    md_file.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        return results

    # Serve built Vite SPA assets if they exist
    if _WEB_DIST_DIR.exists() and (_WEB_DIST_DIR / "index.html").exists():
        # Serve static assets (JS, CSS, etc.)
        assets_dir = _WEB_DIST_DIR / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        _resolved_dist_dir = _WEB_DIST_DIR.resolve()

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str) -> FileResponse:
            """Serve the SPA index.html for all non-API routes."""
            # Check if a static file exists at the path first
            file_path = _WEB_DIST_DIR / full_path
            # Defense-in-depth: verify resolved path stays within web_dist
            if (
                full_path
                and file_path.resolve().is_relative_to(_resolved_dist_dir)
                and file_path.exists()
                and file_path.is_file()
            ):
                return FileResponse(str(file_path))
            return FileResponse(str(_WEB_DIST_DIR / "index.html"))

    return app, auth_token
