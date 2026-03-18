"""Tests for write API endpoints (PUT config, POST runs, GET artifacts)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary repo root with .colonyos/runs/ directory."""
    runs_dir = tmp_path / ".colonyos" / "runs"
    runs_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def write_env(monkeypatch):
    """Enable write mode for tests."""
    monkeypatch.setenv("COLONYOS_WRITE_ENABLED", "1")


def _write_config(repo_root: Path) -> None:
    """Write a minimal config.yaml."""
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
        _write_config(tmp_repo)
        resp = client.put("/api/config", json={"model": "opus"})
        assert resp.status_code == 401

    def test_put_config_wrong_token(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        _write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"model": "opus"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_put_config_valid_token(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
        resp = client.put(
            "/api/config",
            json={"slack": {"enabled": True}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "sensitive" in resp.json()["detail"].lower() or "not allowed" in resp.json()["detail"].lower()

    def test_reject_ceo_persona(self, tmp_repo: Path, write_env):
        client, token = _create_app_with_token(tmp_repo)
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
        _write_config(tmp_repo)
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
