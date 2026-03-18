"""FastAPI application serving the ColonyOS web dashboard API.

All endpoints are read-only (GET). The server wraps existing data-layer
functions from ``stats.py``, ``show.py``, and ``config.py`` and serves
pre-built Vite SPA assets from ``web_dist/``.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path
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
_SENSITIVE_CONFIG_FIELDS = {"slack", "ceo_persona"}


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


def create_app(repo_root: Path) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        repo_root: Path to the repository root containing ``.colonyos/``.

    Returns:
        A configured FastAPI application instance.
    """
    app = FastAPI(
        title="ColonyOS Dashboard",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )

    # CORS for local dev only (Vite dev server on a different port)
    if os.environ.get("COLONYOS_DEV"):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["GET"],
            allow_headers=["Content-Type", "Accept"],
        )

    runs_dir = runs_dir_path(repo_root)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

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

    return app
