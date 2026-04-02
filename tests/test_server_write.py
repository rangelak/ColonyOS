"""Tests for write API endpoints (PUT config, POST runs, GET artifacts)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from conftest import write_config


@pytest.fixture
def write_env(monkeypatch):
    """Enable write mode for tests."""
    monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")


def _create_app_with_token(repo_root: Path):
    """Create app and return (client, token)."""
    from colonyos.server import create_app
    from starlette.testclient import TestClient

    app, token = create_app(repo_root)
    client = TestClient(app)
    return client, token


class TestWriteDisabledByDefault:
    """Write endpoints return 403 when COLONYOS_WRITE_ENABLED is not set."""

    def test_put_config_disabled(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.put("/api/config", json={"model": "opus"})
        assert resp.status_code == 403

    def test_post_runs_disabled(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.post("/api/runs", json={"prompt": "test"})
        assert resp.status_code == 403


class TestAuthRequired:
    """Write endpoints require bearer token."""

    def test_put_config_no_auth(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put("/api/config", json={"model": "opus"})
        assert resp.status_code == 401

    def test_put_config_wrong_token(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"model": "opus"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_put_config_valid_token(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"model": "opus"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_get_endpoints_no_auth_required(self, tmp_repo: Path, write_env):
        """GET endpoints should work without auth even when write mode is on."""
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestPutConfig:
    """Test PUT /api/config endpoint."""

    def test_update_model(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"model": "opus"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "opus"

        # Verify persisted to YAML
        config_path = tmp_repo / ".colonyos" / "config.yaml"
        raw = yaml.safe_load(config_path.read_text())
        assert raw["model"] == "opus"

    def test_update_budget(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"budget": {"per_phase": 10.0, "per_run": 30.0}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["budget"]["per_phase"] == 10.0

    def test_reject_sensitive_fields(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"slack": {"enabled": True}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "sensitive" in resp.json()["detail"].lower() or "not allowed" in resp.json()["detail"].lower()

    def test_reject_ceo_persona(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"ceo_persona": {"role": "CEO", "expertise": "leadership", "perspective": "strategic", "reviewer": False}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


class TestPutPersonas:
    """Test PUT /api/config/personas endpoint."""

    def test_update_personas(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        new_personas = [
            {"role": "UX Designer", "expertise": "UI/UX", "perspective": "user-centric", "reviewer": True},
            {"role": "Backend Dev", "expertise": "APIs", "perspective": "scalability", "reviewer": False},
        ]
        resp = client.put(
            "/api/config/personas",
            json=new_personas,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["personas"]) == 2
        assert data["personas"][0]["role"] == "UX Designer"

    def test_reject_invalid_persona(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        # Missing required field 'perspective'
        resp = client.put(
            "/api/config/personas",
            json=[{"role": "Test", "expertise": "Test"}],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


class TestPostRuns:
    """Test POST /api/runs endpoint."""

    def test_reject_empty_prompt(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        resp = client.post(
            "/api/runs",
            json={"prompt": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_reject_missing_prompt(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        resp = client.post(
            "/api/runs",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_launch_run(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        with patch("colonyos.server.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None
            resp = client.post(
                "/api/runs",
                json={"prompt": "Add login feature"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "launched"
        # run_id is not returned — the orchestrator assigns it asynchronously
        assert "run_id" not in data

    def test_launch_run_rate_limit(self, tmp_repo: Path, write_env):
        """Semaphore prevents concurrent runs."""
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        # Acquire the semaphore externally to simulate an in-progress run
        from colonyos.server import create_app
        app, token2 = create_app(tmp_repo)
        from starlette.testclient import TestClient
        TestClient(app)
        # We need a fresh app; the semaphore is per-app instance.
        # Instead, patch the thread so the first run's semaphore stays held.
        import threading
        hold_semaphore = threading.Event()

        def blocking_run(*args, **kwargs):
            hold_semaphore.wait(timeout=5)

        with patch("colonyos.server.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None
            # First launch succeeds (acquires semaphore)
            resp1 = client.post(
                "/api/runs",
                json={"prompt": "First run"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp1.status_code == 200
            # Second launch should be rejected (semaphore held)
            resp2 = client.post(
                "/api/runs",
                json={"prompt": "Second run"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp2.status_code == 429


class TestGetArtifacts:
    """Test GET /api/artifacts/{path} endpoint."""

    def test_serve_prd_file(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        prd_dir = tmp_repo / "cOS_prds"
        prd_dir.mkdir()
        (prd_dir / "test_prd.md").write_text("# Test PRD\nContent here", encoding="utf-8")

        resp = client.get("/api/artifacts/cOS_prds/test_prd.md")
        assert resp.status_code == 200
        assert "Test PRD" in resp.json()["content"]

    def test_path_traversal_rejected(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        # Use encoded dots to bypass URL normalization
        resp = client.get("/api/artifacts/cOS_prds/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)  # Either blocked or not found

    def test_disallowed_directory(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        resp = client.get("/api/artifacts/src/colonyos/server.py")
        assert resp.status_code == 400

    def test_nonexistent_file(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        resp = client.get("/api/artifacts/cOS_prds/nonexistent.md")
        assert resp.status_code == 404


class TestGetProposals:
    """Test GET /api/proposals endpoint."""

    def test_list_proposals(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        proposals_dir = tmp_repo / "cOS_proposals"
        proposals_dir.mkdir()
        (proposals_dir / "proposal_1.md").write_text("# Proposal 1", encoding="utf-8")

        resp = client.get("/api/proposals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "proposal_1.md"

    def test_empty_proposals(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get("/api/proposals")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetReviews:
    """Test GET /api/reviews endpoint."""

    def test_list_reviews(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        reviews_dir = tmp_repo / "cOS_reviews" / "reviews" / "security_engineer"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "round_1.md").write_text("# Review", encoding="utf-8")

        resp = client.get("/api/reviews")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_empty_reviews(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get("/api/reviews")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAuthVerify:
    """Test GET /api/auth/verify endpoint."""

    def test_valid_token(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        resp = client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_invalid_token(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get(
            "/api/auth/verify",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_no_token(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get("/api/auth/verify")
        assert resp.status_code == 401

    def test_write_disabled(self, tmp_repo: Path, monkeypatch):
        monkeypatch.delenv("COLONYOS_WRITE_ENABLED", raising=False)
        client, _ = _create_app_with_token(tmp_repo)
        resp = client.get("/api/auth/verify")
        assert resp.status_code == 403


class TestArtifactSanitization:
    """Verify artifact content is sanitized before being returned."""

    def test_html_tags_stripped(self, tmp_repo: Path, write_env):
        client, _ = _create_app_with_token(tmp_repo)
        prd_dir = tmp_repo / "cOS_prds"
        prd_dir.mkdir()
        (prd_dir / "xss.md").write_text(
            "Hello <script>alert(1)</script> world", encoding="utf-8"
        )
        resp = client.get("/api/artifacts/cOS_prds/xss.md")
        assert resp.status_code == 200
        content = resp.json()["content"]
        assert "<script>" not in content
        assert "Hello" in content
        assert "world" in content


class TestPauseResumeRateLimit:
    """Test that pause/resume endpoints enforce a cooldown."""

    def test_rapid_pause_returns_429(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        auth = {"Authorization": f"Bearer {token}"}

        # First call should succeed
        resp1 = client.post("/api/daemon/pause", json={}, headers=auth)
        assert resp1.status_code == 200

        # Immediate second call should be rate limited
        resp2 = client.post("/api/daemon/pause", json={}, headers=auth)
        assert resp2.status_code == 429

    def test_rapid_resume_returns_429(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        auth = {"Authorization": f"Bearer {token}"}

        resp1 = client.post("/api/daemon/resume", json={}, headers=auth)
        assert resp1.status_code == 200

        resp2 = client.post("/api/daemon/resume", json={}, headers=auth)
        assert resp2.status_code == 429


class TestCORSOriginValidation:
    """Test that malformed and wildcard CORS origins are rejected."""

    def test_wildcard_origin_rejected(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "*")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "http://evil.com"},
        )
        assert resp.status_code == 200
        # Wildcard should not be in CORS — no allow-origin header for evil.com
        assert resp.headers.get("access-control-allow-origin") is None

    def test_malformed_origin_rejected(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "not-a-url,ftp://bad.com")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "not-a-url"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") is None

    def test_valid_origin_accepted(self, tmp_repo: Path, monkeypatch):
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "https://dashboard.example.com")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get(
            "/api/health",
            headers={"Origin": "https://dashboard.example.com"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://dashboard.example.com"


class TestHealthzSubdomainAuth:
    """Test that /healthz requires auth in subdomain mode."""

    def test_healthz_no_auth_localhost(self, tmp_repo: Path, monkeypatch):
        """Without allowed origins, healthz should not require auth."""
        monkeypatch.delenv("COLONYOS_ALLOWED_ORIGINS", raising=False)
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, _ = create_app(tmp_repo)
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code in (200, 503)

    def test_healthz_requires_auth_subdomain(self, tmp_repo: Path, monkeypatch):
        """With allowed origins set, healthz should require auth."""
        monkeypatch.setenv("COLONYOS_ALLOWED_ORIGINS", "https://dashboard.example.com")
        from colonyos.server import create_app
        from starlette.testclient import TestClient

        app, token = create_app(tmp_repo)
        client = TestClient(app)

        # No auth → 401
        resp = client.get("/api/healthz")
        assert resp.status_code == 401

        # With auth → success
        resp2 = client.get(
            "/api/healthz",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code in (200, 503)


class TestSemaphoreSafety:
    """Verify semaphore is released if Thread creation fails."""

    def test_semaphore_released_on_thread_error(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        write_config(tmp_repo)
        with patch("colonyos.server.threading.Thread", side_effect=RuntimeError("boom")):
            resp = client.post(
                "/api/runs",
                json={"prompt": "test prompt"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 500

        # Semaphore should be released — a subsequent request should not get 429
        with patch("colonyos.server.threading.Thread") as mock_thread:
            mock_thread.return_value.start.return_value = None
            resp2 = client.post(
                "/api/runs",
                json={"prompt": "test prompt 2"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp2.status_code == 200
