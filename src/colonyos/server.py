"""FastAPI application serving the ColonyOS web dashboard API.

All endpoints are read-only (GET). The server wraps existing data-layer
functions from ``stats.py``, ``show.py``, and ``config.py`` and serves
pre-built Vite SPA assets from ``web_dist/``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path
from colonyos.show import (
    compute_show_result,
    resolve_run_id,
    validate_run_id_input,
)
from colonyos.stats import compute_stats, load_run_logs

logger = logging.getLogger(__name__)

# Path to the built Vite SPA assets (committed to repo)
_WEB_DIST_DIR = Path(__file__).parent / "web_dist"


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Serialize a ColonyConfig to a JSON-safe dict."""
    result: dict[str, Any] = {
        "model": config.model,
        "phase_models": dict(config.phase_models),
        "budget": asdict(config.budget),
        "phases": asdict(config.phases),
        "branch_prefix": config.branch_prefix,
        "prds_dir": config.prds_dir,
        "tasks_dir": config.tasks_dir,
        "reviews_dir": config.reviews_dir,
        "proposals_dir": config.proposals_dir,
        "max_fix_iterations": config.max_fix_iterations,
        "auto_approve": config.auto_approve,
        "learnings": asdict(config.learnings),
        "ci_fix": asdict(config.ci_fix),
        "vision": config.vision,
    }
    if config.project:
        result["project"] = {
            "name": config.project.name,
            "description": config.project.description,
            "stack": config.project.stack,
        }
    else:
        result["project"] = None
    result["personas"] = [
        {
            "role": p.role,
            "expertise": p.expertise,
            "perspective": p.perspective,
            "reviewer": p.reviewer,
        }
        for p in config.personas
    ]
    return result


def _stats_result_to_dict(result: Any) -> dict[str, Any]:
    """Serialize a StatsResult to a JSON-safe dict."""
    return {
        "summary": asdict(result.summary),
        "cost_breakdown": [asdict(r) for r in result.cost_breakdown],
        "failure_hotspots": [asdict(r) for r in result.failure_hotspots],
        "review_loop": asdict(result.review_loop),
        "duration_stats": [asdict(r) for r in result.duration_stats],
        "recent_trend": [asdict(r) for r in result.recent_trend],
        "phase_detail": [asdict(r) for r in result.phase_detail],
        "phase_filter": result.phase_filter,
        "model_usage": [asdict(r) for r in result.model_usage],
    }


def _show_result_to_dict(result: Any) -> dict[str, Any]:
    """Serialize a ShowResult to a JSON-safe dict."""
    return {
        "header": asdict(result.header),
        "timeline": [asdict(e) for e in result.timeline],
        "review_summary": asdict(result.review_summary) if result.review_summary else None,
        "has_decision": result.has_decision,
        "decision_success": result.decision_success,
        "has_ci_fix": result.has_ci_fix,
        "ci_fix_attempts": result.ci_fix_attempts,
        "ci_fix_final_success": result.ci_fix_final_success,
        "phase_filter": result.phase_filter,
        "phase_detail": [asdict(e) for e in result.phase_detail],
    }


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

    # CORS for local dev (Vite dev server on different port)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    runs_dir = runs_dir_path(repo_root)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        logs = load_run_logs(runs_dir)
        # Return lightweight summaries (the raw dicts from JSON files)
        return logs

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            validate_run_id_input(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            resolved = resolve_run_id(runs_dir, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        if isinstance(resolved, list):
            raise HTTPException(
                status_code=400,
                detail=f"Ambiguous run ID {run_id!r}: matches {resolved}",
            )

        from colonyos.show import load_single_run

        try:
            run_data = load_single_run(runs_dir, resolved)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        show_result = compute_show_result(run_data)
        return _show_result_to_dict(show_result)

    @app.get("/api/stats")
    def get_stats() -> dict[str, Any]:
        logs = load_run_logs(runs_dir)
        result = compute_stats(logs)
        return _stats_result_to_dict(result)

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

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str) -> FileResponse:
            """Serve the SPA index.html for all non-API routes."""
            # Check if a static file exists at the path first
            file_path = _WEB_DIST_DIR / full_path
            if full_path and file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_WEB_DIST_DIR / "index.html"))

    return app
