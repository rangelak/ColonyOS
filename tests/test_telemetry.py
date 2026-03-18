"""Tests for the telemetry module."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from colonyos.config import PostHogConfig
from colonyos.telemetry import (
    _ALLOWED_PROPERTIES,
    _filter_properties,
    _generate_anonymous_id,
    capture,
    capture_cli_command,
    capture_phase_completed,
    capture_run_completed,
    capture_run_failed,
    capture_run_started,
    init_telemetry,
    is_initialized,
    shutdown,
)


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    """Reset module-level telemetry state before each test."""
    import colonyos.telemetry as mod

    mod._posthog_client = None
    mod._enabled = False
    mod._distinct_id = ""
    yield
    mod._posthog_client = None
    mod._enabled = False
    mod._distinct_id = ""


class TestFilterProperties:
    def test_allowed_keys_pass_through(self):
        props = {"model": "sonnet", "cost_usd": 1.23, "success": True}
        assert _filter_properties(props) == props

    def test_blocked_keys_stripped(self):
        props = {
            "model": "sonnet",
            "prompt": "secret prompt",
            "branch_name": "feat/secret",
            "error": "traceback details",
        }
        result = _filter_properties(props)
        assert result == {"model": "sonnet"}
        assert "prompt" not in result
        assert "branch_name" not in result
        assert "error" not in result

    def test_empty_dict(self):
        assert _filter_properties({}) == {}

    def test_all_blocked(self):
        props = {"prompt": "secret", "branch_name": "x", "artifacts": {}}
        assert _filter_properties(props) == {}


class TestAnonymousIdGeneration:
    def test_generates_consistent_id(self, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        id1 = _generate_anonymous_id(config_dir)
        id2 = _generate_anonymous_id(config_dir)
        assert id1 == id2
        assert len(id1) == 36  # UUID4 format (xxxxxxxx-xxxx-4xxx-xxxx-xxxxxxxxxxxx)

    def test_generates_random_uuid(self, tmp_path: Path):
        """IDs from different directories should differ (random UUID, not deterministic)."""
        dir1 = tmp_path / "a"
        dir1.mkdir()
        dir2 = tmp_path / "b"
        dir2.mkdir()
        id1 = _generate_anonymous_id(dir1)
        id2 = _generate_anonymous_id(dir2)
        assert id1 != id2

    def test_persists_to_file(self, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        anonymous_id = _generate_anonymous_id(config_dir)
        stored = (config_dir / "telemetry_id").read_text(encoding="utf-8").strip()
        assert stored == anonymous_id

    def test_reads_from_existing_file(self, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        (config_dir / "telemetry_id").write_text("custom-id-123\n", encoding="utf-8")
        assert _generate_anonymous_id(config_dir) == "custom-id-123"


class TestInitTelemetry:
    def test_disabled_config_stays_disabled(self, tmp_path: Path):
        import colonyos.telemetry as mod

        init_telemetry(PostHogConfig(enabled=False), tmp_path)
        assert mod._enabled is False
        assert mod._posthog_client is None

    def test_enabled_but_no_api_key(self, tmp_path: Path):
        import colonyos.telemetry as mod

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COLONYOS_POSTHOG_API_KEY", None)
            init_telemetry(PostHogConfig(enabled=True), tmp_path)
        assert mod._enabled is False

    def test_enabled_but_sdk_not_installed(self, tmp_path: Path):
        import colonyos.telemetry as mod

        with patch.dict(os.environ, {"COLONYOS_POSTHOG_API_KEY": "phc_test123"}):
            with patch.dict("sys.modules", {"posthog": None}):
                init_telemetry(PostHogConfig(enabled=True), tmp_path)
        assert mod._enabled is False

    def test_enabled_with_key_and_sdk(self, tmp_path: Path):
        import colonyos.telemetry as mod

        mock_client = MagicMock()
        mock_posthog_module = MagicMock()
        mock_posthog_module.Posthog.return_value = mock_client
        with patch.dict(os.environ, {"COLONYOS_POSTHOG_API_KEY": "phc_test123"}):
            with patch.dict("sys.modules", {"posthog": mock_posthog_module}):
                init_telemetry(PostHogConfig(enabled=True), tmp_path / ".colonyos")
        assert mod._enabled is True
        assert mod._posthog_client is mock_client
        mock_posthog_module.Posthog.assert_called_once_with(
            "phc_test123", host="https://us.i.posthog.com"
        )

    def test_custom_host(self, tmp_path: Path):
        import colonyos.telemetry as mod

        mock_client = MagicMock()
        mock_posthog_module = MagicMock()
        mock_posthog_module.Posthog.return_value = mock_client
        with patch.dict(os.environ, {
            "COLONYOS_POSTHOG_API_KEY": "phc_test123",
            "COLONYOS_POSTHOG_HOST": "https://custom.posthog.com",
        }):
            with patch.dict("sys.modules", {"posthog": mock_posthog_module}):
                init_telemetry(PostHogConfig(enabled=True), tmp_path)
        mock_posthog_module.Posthog.assert_called_once_with(
            "phc_test123", host="https://custom.posthog.com"
        )

    def test_skips_reinit_when_already_enabled(self, tmp_path: Path):
        """init_telemetry is a no-op when already initialized."""
        import colonyos.telemetry as mod

        mock_client = MagicMock()
        mod._posthog_client = mock_client
        mod._enabled = True
        mod._distinct_id = "original-id"

        init_telemetry(PostHogConfig(enabled=True), tmp_path)
        # State should be unchanged
        assert mod._distinct_id == "original-id"
        assert mod._posthog_client is mock_client

    def test_is_initialized(self, tmp_path: Path):
        import colonyos.telemetry as mod

        assert is_initialized() is False
        mod._enabled = True
        assert is_initialized() is True


class TestCapture:
    def test_noop_when_disabled(self):
        """capture() should silently no-op when telemetry is disabled."""
        # Should not raise
        capture("test_event", {"model": "sonnet"})

    def test_captures_when_enabled(self, tmp_path: Path):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mod._posthog_client = mock_posthog
        mod._enabled = True
        mod._distinct_id = "test-id"

        capture("test_event", {"model": "sonnet", "cost_usd": 1.0})

        mock_posthog.capture.assert_called_once_with(
            distinct_id="test-id",
            event="test_event",
            properties={"model": "sonnet", "cost_usd": 1.0},
        )

    def test_strips_disallowed_properties(self, tmp_path: Path):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mod._posthog_client = mock_posthog
        mod._enabled = True
        mod._distinct_id = "test-id"

        capture("test_event", {"model": "sonnet", "prompt": "secret"})

        mock_posthog.capture.assert_called_once_with(
            distinct_id="test-id",
            event="test_event",
            properties={"model": "sonnet"},
        )

    def test_silent_on_exception(self, tmp_path: Path):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mock_posthog.capture.side_effect = RuntimeError("network error")
        mod._posthog_client = mock_posthog
        mod._enabled = True
        mod._distinct_id = "test-id"

        # Should not raise
        capture("test_event", {"model": "sonnet"})


class TestShutdown:
    def test_noop_when_disabled(self):
        # Should not raise
        shutdown()

    def test_calls_sdk_shutdown(self):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mod._posthog_client = mock_posthog
        mod._enabled = True

        shutdown()
        mock_posthog.shutdown.assert_called_once()

    def test_silent_on_exception(self):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mock_posthog.shutdown.side_effect = RuntimeError("flush failed")
        mod._posthog_client = mock_posthog
        mod._enabled = True

        # Should not raise
        shutdown()

    def test_idempotent_double_shutdown(self):
        """Second shutdown call should be a silent no-op."""
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mod._posthog_client = mock_posthog
        mod._enabled = True

        shutdown()
        shutdown()  # second call — should not raise or call SDK again
        mock_posthog.shutdown.assert_called_once()


class TestConvenienceFunctions:
    """Test that convenience functions call capture with correct event names and properties."""

    @pytest.fixture(autouse=True)
    def _enable_telemetry(self):
        import colonyos.telemetry as mod

        mock_posthog = MagicMock()
        mod._posthog_client = mock_posthog
        mod._enabled = True
        mod._distinct_id = "test-id"
        self.mock_posthog = mock_posthog

    def test_capture_run_started(self):
        capture_run_started(
            model="sonnet",
            phase_config={"plan": True, "implement": True, "review": True, "deliver": True},
            persona_count=3,
            budget_per_run=15.0,
            colonyos_version="1.0.0",
        )
        call_args = self.mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "run_started"
        props = call_args.kwargs["properties"]
        assert props["model"] == "sonnet"
        assert props["persona_count"] == 3
        assert props["colonyos_version"] == "1.0.0"

    def test_capture_phase_completed(self):
        capture_phase_completed(
            phase_name="plan",
            model="opus",
            cost_usd=2.5,
            duration_ms=30000,
            success=True,
        )
        call_args = self.mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "phase_completed"
        props = call_args.kwargs["properties"]
        assert props["phase_name"] == "plan"
        assert props["success"] is True

    def test_capture_run_completed(self):
        capture_run_completed(
            status="completed",
            total_cost_usd=5.0,
            total_duration_ms=120000,
            phase_count=4,
            fix_iteration_count=1,
            colonyos_version="1.0.0",
        )
        call_args = self.mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "run_completed"
        props = call_args.kwargs["properties"]
        assert props["total_cost_usd"] == 5.0
        assert props["fix_iteration_count"] == 1

    def test_capture_run_failed(self):
        capture_run_failed(
            failing_phase_name="implement",
            colonyos_version="1.0.0",
        )
        call_args = self.mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "run_failed"
        props = call_args.kwargs["properties"]
        assert props["failing_phase_name"] == "implement"

    def test_capture_cli_command(self):
        capture_cli_command(
            command_name="run",
            colonyos_version="1.0.0",
        )
        call_args = self.mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "cli_command"
        props = call_args.kwargs["properties"]
        assert props["command_name"] == "run"


class TestAllowlist:
    """Verify the allowlist is comprehensive and doesn't include sensitive fields."""

    def test_no_sensitive_fields_in_allowlist(self):
        sensitive = {
            "prompt", "branch_name", "prd_rel", "task_rel",
            "source_issue", "source_issue_url", "error",
            "artifacts", "project_name", "project_description",
            "persona_content",
        }
        assert _ALLOWED_PROPERTIES.isdisjoint(sensitive)

    def test_all_expected_fields_present(self):
        expected = {
            "model", "phase_config", "persona_count", "budget_per_run",
            "colonyos_version", "phase_name", "cost_usd", "duration_ms",
            "success", "status", "total_cost_usd", "total_duration_ms",
            "phase_count", "fix_iteration_count", "failing_phase_name",
            "command_name",
        }
        assert expected == _ALLOWED_PROPERTIES


class TestDoctorPostHogCheck:
    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_posthog_key_present(self, tmp_repo: Path) -> None:
        from colonyos.doctor import run_doctor_checks

        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"posthog": {"enabled": True}}),
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"COLONYOS_POSTHOG_API_KEY": "phc_test123"}):
            results = run_doctor_checks(tmp_repo)
        ph_checks = [(n, p) for n, p, _ in results if n == "PostHog API key"]
        assert len(ph_checks) == 1
        assert ph_checks[0][1] is True

    def test_posthog_key_missing(self, tmp_repo: Path) -> None:
        from colonyos.doctor import run_doctor_checks

        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({"posthog": {"enabled": True}}),
            encoding="utf-8",
        )
        env_copy = os.environ.copy()
        env_copy.pop("COLONYOS_POSTHOG_API_KEY", None)
        with patch.dict("os.environ", env_copy, clear=True):
            results = run_doctor_checks(tmp_repo)
        ph_checks = [(n, p, h) for n, p, h in results if n == "PostHog API key"]
        assert len(ph_checks) == 1
        assert ph_checks[0][1] is False
        assert "COLONYOS_POSTHOG_API_KEY" in ph_checks[0][2]

    def test_posthog_check_skipped_when_disabled(self, tmp_repo: Path) -> None:
        from colonyos.doctor import run_doctor_checks

        results = run_doctor_checks(tmp_repo)
        ph_checks = [n for n, _, _ in results if n == "PostHog API key"]
        assert len(ph_checks) == 0
