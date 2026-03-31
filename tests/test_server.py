"""Tests for the ColonyOS web dashboard API server."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from conftest import write_config


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


class TestImportGuard:
    """Verify the server module can be imported when fastapi is available."""

    def test_import_server(self):
        from colonyos.server import create_app

        assert callable(create_app)


class TestHealthEndpoint:
    def test_health(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_runs(self, tmp_repo: Path, sample_run_data: dict):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        runs_dir = tmp_repo / ".colonyos" / "runs"
        _write_run(runs_dir, sample_run_data)

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/run-20260318_120000-abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["header"]["run_id"] == "run-20260318_120000-abc123"
        assert "timeline" in data

    def test_missing_run(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/run-nonexistent")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        # Use dotdot without slashes — slashes are consumed by the HTTP router
        resp = client.get("/api/runs/..%5C..%5Cetc%5Cpasswd")
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    def test_backslash_traversal_rejected(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/runs/..\\..\\etc\\passwd")
        assert resp.status_code == 400


class TestStatsEndpoint:
    def test_empty_stats(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data

    def test_config_with_yaml(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        write_config(tmp_repo)

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue_id"] == "q-001"
        assert len(data["items"]) == 1


class TestReadOnly:
    """Verify write methods are blocked when COLONYOS_WRITE_ENABLED is not set."""

    def test_post_runs_blocked(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.post("/api/runs", json={})
        assert resp.status_code == 403

    def test_put_config_blocked(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.put("/api/config", json={})
        assert resp.status_code == 403

    def test_post_runs_returns_conflict_when_repo_runtime_busy(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.runtime_lock import RuntimeBusyError, RuntimeProcessRecord
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, auth_token = create_app(tmp_repo)
        client = TestClient(app)
        busy = RuntimeBusyError(
            tmp_repo,
            RuntimeProcessRecord(
                pid=7001,
                mode="daemon",
                cwd=str(tmp_repo),
                started_at="2026-03-30T00:00:00+00:00",
                command="colonyos daemon",
            ),
        )
        with patch("colonyos.server.RepoRuntimeGuard.acquire", side_effect=busy):
            resp = client.post(
                "/api/runs",
                json={"prompt": "Add feature"},
                headers={"Authorization": f"Bearer {auth_token}"},
            )

        assert resp.status_code == 409

    def test_delete_run_not_allowed(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
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

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        # Sensitive fields like slack should not be exposed
        assert "slack" not in data

    def test_config_excludes_ceo_persona(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "ceo_persona" not in data

    def test_sensitive_fields_constant_used(self):
        """Verify _SENSITIVE_CONFIG_FIELDS is actively used in _config_to_dict."""
        from colonyos.server import _SENSITIVE_CONFIG_FIELDS, _config_to_dict
        from colonyos.config import ColonyConfig

        config = ColonyConfig()
        result = _config_to_dict(config)
        for field_name in _SENSITIVE_CONFIG_FIELDS:
            assert field_name not in result


class TestCORSDevOnly:
    """Verify CORS middleware is only active when COLONYOS_DEV is set."""

    def test_no_cors_headers_in_production(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_DEV", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_cors_headers_in_dev(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_DEV", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


class TestErrorMessageSafety:
    """Verify error responses do not leak internal paths."""

    def test_invalid_run_id_no_path_leak(self, tmp_repo: Path):
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        # Use dotdot without slashes — slashes are consumed by the HTTP router
        resp = client.get("/api/runs/..%5C..%5Cetc%5Cpasswd")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        # Should not contain filesystem paths
        assert "Invalid" in detail
        assert "/" not in detail or "Run" in detail  # only the generic message


class TestDaemonPauseResume:
    """Tests for POST /api/daemon/pause and POST /api/daemon/resume endpoints."""

    def test_pause_requires_write_enabled(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.post("/api/daemon/pause")
        assert resp.status_code == 403

    def test_resume_requires_write_enabled(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.post("/api/daemon/resume")
        assert resp.status_code == 403

    def test_pause_requires_valid_token(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.post(
            "/api/daemon/pause",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_pause_toggles_state_disk_fallback(self, tmp_repo: Path, monkeypatch):
        """When no live daemon, pause/resume should toggle state on disk."""
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, auth_token = create_app(tmp_repo)
        client = TestClient(app)

        # Pause
        resp = client.post(
            "/api/daemon/pause",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paused"] is True

        # Verify healthz also reflects paused state
        resp = client.get("/healthz")
        health = resp.json()
        assert health["paused"] is True

    def test_resume_toggles_state_disk_fallback(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, auth_token = create_app(tmp_repo)
        client = TestClient(app)

        # Pause first
        client.post(
            "/api/daemon/pause",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        # Then resume
        resp = client.post(
            "/api/daemon/resume",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paused"] is False

    def test_pause_with_live_daemon(self, tmp_repo: Path, monkeypatch):
        """When a live daemon instance is attached, pause should toggle it."""
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, auth_token = create_app(tmp_repo)

        # Simulate a live daemon instance
        mock_daemon = MagicMock()
        mock_daemon.pause.return_value = None
        mock_daemon.get_health.return_value = {
            "status": "degraded",
            "heartbeat_age_seconds": 1.0,
            "queue_depth": 0,
            "daily_spend_usd": 0.0,
            "daily_budget_remaining_usd": 500.0,
            "circuit_breaker_active": False,
            "paused": True,
            "pipeline_running": False,
            "total_items_today": 0,
            "consecutive_failures": 0,
        }
        app.state.daemon_instance = mock_daemon

        client = TestClient(app)
        resp = client.post(
            "/api/daemon/pause",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paused"] is True
        mock_daemon.pause.assert_called_once()

    def test_resume_with_live_daemon(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, auth_token = create_app(tmp_repo)

        mock_daemon = MagicMock()
        mock_daemon.resume.return_value = None
        mock_daemon.get_health.return_value = {
            "status": "healthy",
            "heartbeat_age_seconds": 1.0,
            "queue_depth": 0,
            "daily_spend_usd": 0.0,
            "daily_budget_remaining_usd": 500.0,
            "circuit_breaker_active": False,
            "paused": False,
            "pipeline_running": False,
            "total_items_today": 0,
            "consecutive_failures": 0,
        }
        app.state.daemon_instance = mock_daemon

        client = TestClient(app)
        resp = client.post(
            "/api/daemon/resume",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paused"] is False
        mock_daemon.resume.assert_called_once()


class TestConfigurableCORS:
    """Tests for COLONYOS_ALLOWED_ORIGINS configurable CORS."""

    def test_custom_origins_applied(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "https://colonyos.myapp.com,https://ops.example.com")
        monkeypatch.delenv("COLONYOS_DEV", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "https://colonyos.myapp.com"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://colonyos.myapp.com"

    def test_custom_origins_rejects_unknown(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "https://colonyos.myapp.com")
        monkeypatch.delenv("COLONYOS_DEV", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "https://evil.com"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_no_origins_env_no_cors(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("COLONYOS_DEV", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_dev_and_custom_origins_combined(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_DEV", "1")
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "https://colonyos.myapp.com")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        # Dev origin should still work
        resp = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


class TestSPAPathTraversal:
    """Verify SPA catch-all route blocks path traversal."""

    def test_spa_path_traversal_returns_index(self, tmp_repo: Path):
        from colonyos.server import create_app, _WEB_DIST_DIR
        from starlette.testclient import TestClient

        if not _WEB_DIST_DIR.exists() or not (_WEB_DIST_DIR / "index.html").exists():
            pytest.skip("web_dist not built")

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        # Attempt path traversal via the SPA catch-all
        resp = client.get("/..%2F..%2Fetc%2Fpasswd")
        # Should return 200 with index.html, not serve arbitrary files
        assert resp.status_code == 200
