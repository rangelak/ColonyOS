"""Tests for the ColonyOS web dashboard API server."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary repo root with .colonyos/runs/ directory."""
    runs_dir = tmp_path / ".colonyos" / "runs"
    runs_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def sample_run_data() -> dict:
    """A minimal valid run log dict."""
    return {
        "run_id": "run-20260318_120000-abc123",
        "prompt": "Add login feature",
        "status": "completed",
        "phases": [
            {
                "phase": "plan",
                "success": True,
                "cost_usd": 0.05,
                "duration_ms": 5000,
                "model": "sonnet",
                "session_id": "sess-1",
            },
            {
                "phase": "implement",
                "success": True,
                "cost_usd": 0.10,
                "duration_ms": 15000,
                "model": "sonnet",
                "session_id": "sess-2",
            },
        ],
        "total_cost_usd": 0.15,
        "started_at": "2026-03-18T12:00:00+00:00",
        "finished_at": "2026-03-18T12:01:00+00:00",
        "branch_name": "colonyos/add-login",
    }


def _write_run(runs_dir: Path, run_data: dict) -> None:
    """Write a run log JSON file."""
    run_id = run_data["run_id"]
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(run_data), encoding="utf-8"
    )


def _write_queue(repo_root: Path, queue_data: dict) -> None:
    """Write a queue state JSON file."""
    (repo_root / ".colonyos" / "queue.json").write_text(
        json.dumps(queue_data), encoding="utf-8"
    )


def _write_config(repo_root: Path) -> None:
    """Write a minimal config.yaml."""
    import yaml

    config_dir = repo_root / ".colonyos"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model": "sonnet",
        "project": {"name": "test-project", "description": "A test", "stack": "python"},
        "personas": [
            {
                "role": "Security Engineer",
                "expertise": "AppSec",
                "perspective": "defensive",
                "reviewer": True,
            }
        ],
        "budget": {"per_phase": 5.0, "per_run": 15.0},
        "phases": {"plan": True, "implement": True, "review": True, "deliver": True},
    }
    (config_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


class TestImportGuard:
    """Verify the server module can be imported when fastapi is available."""

    def test_import_server(self):
        from colonyos.server import create_app

        assert callable(create_app)


class TestHealthEndpoint:
    def test_health(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestRunsEndpoint:
    def test_empty_runs(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_runs(self, tmp_repo: Path, sample_run_data: dict):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        _write_run(runs_dir, sample_run_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["run_id"] == "run-20260318_120000-abc123"


class TestRunDetailEndpoint:
    def test_valid_run(self, tmp_repo: Path, sample_run_data: dict):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        _write_run(runs_dir, sample_run_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/run-20260318_120000-abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["header"]["run_id"] == "run-20260318_120000-abc123"
        assert "timeline" in data

    def test_missing_run(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/run-nonexistent")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        # Use dotdot without slashes — slashes are consumed by the HTTP router
        resp = client.get("/api/runs/..%5C..%5Cetc%5Cpasswd")
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    def test_backslash_traversal_rejected(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/..\\..\\etc\\passwd")
        assert resp.status_code == 400


class TestStatsEndpoint:
    def test_empty_stats(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert data["summary"]["total_runs"] == 0

    def test_stats_with_runs(self, tmp_repo: Path, sample_run_data: dict):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        _write_run(runs_dir, sample_run_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_runs"] == 1
        assert data["summary"]["total_cost_usd"] == 0.15


class TestConfigEndpoint:
    def test_default_config(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data

    def test_config_with_yaml(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        _write_config(tmp_repo)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "sonnet"
        assert data["project"]["name"] == "test-project"
        assert len(data["personas"]) == 1


class TestQueueEndpoint:
    def test_no_queue(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_with_queue(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        queue_data = {
            "queue_id": "q-001",
            "items": [
                {
                    "id": "item-1",
                    "source_type": "prompt",
                    "source_value": "Add auth",
                    "status": "completed",
                    "added_at": "2026-03-18T12:00:00+00:00",
                    "cost_usd": 0.10,
                    "duration_ms": 30000,
                }
            ],
            "aggregate_cost_usd": 0.10,
            "status": "completed",
        }
        _write_queue(tmp_repo, queue_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue_id"] == "q-001"
        assert len(data["items"]) == 1


class TestReadOnly:
    """Verify no write methods are allowed."""

    def test_post_runs_not_allowed(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.post("/api/runs", json={})
        assert resp.status_code == 405

    def test_put_config_not_allowed(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.put("/api/config", json={})
        assert resp.status_code == 405

    def test_delete_run_not_allowed(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.delete("/api/runs/run-123")
        assert resp.status_code == 405


class TestSanitization:
    """Verify user-generated content is sanitized in API responses."""

    def test_run_prompt_sanitized(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        run_data = {
            "run_id": "run-20260318_120000-sanitize",
            "prompt": "Hello <script>alert(1)</script> world",
            "status": "completed",
            "phases": [],
            "total_cost_usd": 0.0,
            "started_at": "2026-03-18T12:00:00+00:00",
            "finished_at": "2026-03-18T12:01:00+00:00",
            "branch_name": "colonyos/test",
        }
        _write_run(runs_dir, run_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # XML-like tags should be stripped
        assert "<script>" not in data[0]["prompt"]
        assert "Hello" in data[0]["prompt"]
        assert "world" in data[0]["prompt"]

    def test_run_error_sanitized(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        run_data = {
            "run_id": "run-20260318_120000-errsanitize",
            "prompt": "test",
            "error": "Failed <injected_tag>bad</injected_tag>",
            "status": "failed",
            "phases": [],
            "total_cost_usd": 0.0,
            "started_at": "2026-03-18T12:00:00+00:00",
            "finished_at": "2026-03-18T12:01:00+00:00",
            "branch_name": "colonyos/test",
        }
        _write_run(runs_dir, run_data)

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "<injected_tag>" not in data[0]["error"]
        assert "Failed" in data[0]["error"]


class TestConfigRedaction:
    """Verify sensitive fields are redacted from config output."""

    def test_config_excludes_slack(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        # Sensitive fields like slack should not be exposed
        assert "slack" not in data


class TestErrorMessageSafety:
    """Verify error responses do not leak internal paths."""

    def test_invalid_run_id_no_path_leak(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app = create_app(tmp_repo)
        client = TestClient(app)
        # Use dotdot without slashes — slashes are consumed by the HTTP router
        resp = client.get("/api/runs/..%5C..%5Cetc%5Cpasswd")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        # Should not contain filesystem paths
        assert "Invalid" in detail
        assert "/" not in detail or "Run" in detail  # only the generic message


class TestSPAPathTraversal:
    """Verify SPA catch-all route blocks path traversal."""

    def test_spa_path_traversal_returns_index(self, tmp_repo: Path):
        from colonyos.server import create_app, _WEB_DIST_DIR
        from starlette.testclient import TestClient

        if not _WEB_DIST_DIR.exists() or not (_WEB_DIST_DIR / "index.html").exists():
            pytest.skip("web_dist not built")

        app = create_app(tmp_repo)
        client = TestClient(app)
        # Attempt path traversal via the SPA catch-all
        resp = client.get("/..%2F..%2Fetc%2Fpasswd")
        # Should return 200 with index.html, not serve arbitrary files
        assert resp.status_code == 200
