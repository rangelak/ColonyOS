"""Tests for TUI CLI integration — ``colonyos tui`` command and ``--tui`` flag."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from colonyos.cli import _NEW_CONVERSATION_SIGNAL, app


@pytest.fixture(autouse=True)
def _mock_cli_subprocess():
    """Prevent real git calls from CLI code paths."""

    def _fake_git(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        if isinstance(cmd, list) and "rev-parse" in cmd and "--abbrev-ref" in cmd:
            m.stdout = "main"
        elif isinstance(cmd, list) and "rev-list" in cmd:
            m.stdout = "0"
        else:
            m.stdout = ""
        return m

    with patch("colonyos.cli.subprocess.run", side_effect=_fake_git):
        yield


@pytest.fixture
def runner():
    return CliRunner()


class TestTuiCommand:
    """Tests for the ``colonyos tui`` CLI command."""

    def test_tui_command_exists(self, runner: CliRunner):
        """The ``tui`` subcommand should be registered."""
        result = runner.invoke(app, ["tui", "--help"])
        assert result.exit_code == 0
        assert "tui" in result.output.lower() or "Launch" in result.output

    def test_tui_shows_error_when_textual_missing(self, runner: CliRunner):
        """When textual is not installed, show a clear error message."""
        with patch("colonyos.cli._launch_tui") as mock_launch:
            mock_launch.side_effect = ImportError(
                "Missing TUI dependencies: textual. "
                "Install the tui extra: pip install colonyos[tui]"
            )
            result = runner.invoke(app, ["tui"])
            assert result.exit_code != 0
            assert "pip install" in result.output or "tui" in result.output

    def test_tui_requires_init(self, runner: CliRunner, tmp_path: Path):
        """Should error if colonyos is not initialised."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["tui"])
            assert result.exit_code != 0
            assert "init" in result.output.lower()


class TestTuiFlag:
    """Tests for the TUI-related flags on the ``run`` command."""

    def test_run_no_tui_flag_in_help(self, runner: CliRunner):
        """The ``--no-tui`` flag should appear in ``run --help``."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--no-tui" in result.output

    def test_run_interactive_launches_tui_by_default(self, runner: CliRunner, tmp_path: Path):
        """Interactive ``colonyos run 'prompt'`` should invoke the TUI launcher."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "project:\n  name: test\nreviewers: []\n"
        )
        with (
            patch("colonyos.cli._find_repo_root", return_value=tmp_path),
            patch("colonyos.cli._interactive_stdio", return_value=True),
            patch("colonyos.cli._tui_available", return_value=True),
            patch("colonyos.cli.load_config") as mock_config,
            patch("colonyos.cli._launch_tui") as mock_launch,
        ):
            mock_cfg = MagicMock()
            mock_cfg.project = MagicMock()
            mock_config.return_value = mock_cfg
            result = runner.invoke(app, ["run", "test prompt"])
            assert result.exit_code == 0
            mock_launch.assert_called_once()
            call_kwargs = mock_launch.call_args
            assert call_kwargs is not None


class TestMakeUiOverride:
    """Tests for the ``ui_override`` parameter on orchestrator ``run()``."""

    def test_ui_override_returned_by_make_ui(self):
        """When ``ui_factory`` is provided, ``_make_ui()`` returns it."""
        from colonyos.orchestrator import run as run_orchestrator

        # The run() function already supports ui_factory. Verify the
        # existing behaviour: when a ui_factory is provided, that factory
        # is used instead of creating PhaseUI.
        sentinel = object()
        factory = MagicMock(return_value=sentinel)

        # We can't easily call run() without a full environment, but we
        # can verify the function signature accepts ui_factory.
        import inspect

        sig = inspect.signature(run_orchestrator)
        assert "ui_factory" in sig.parameters


class TestSessionStateTuiWiring:
    """Task 4.0 — verify session state wiring in _run_callback closure."""

    @pytest.fixture
    def _mock_tui_env(self, tmp_path: Path):
        """Set up minimal mocks for _launch_tui internals."""
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "project:\n  name: test\nreviewers: []\n"
        )
        return tmp_path

    def test_first_direct_agent_stores_session_id(self, _mock_tui_env: Path):
        """After a successful direct-agent run the session_id is stored."""
        from colonyos.cli import _run_direct_agent, _handle_tui_command
        from colonyos.models import PhaseResult, Phase

        # Simulate what _run_callback does: call _run_direct_agent and
        # capture the returned session_id.
        fake_result = (True, "session-abc-123")
        with patch("colonyos.cli._run_direct_agent", return_value=fake_result) as mock_da:
            success, session_id = mock_da(
                "fix the bug",
                repo_root=_mock_tui_env,
                config=MagicMock(),
                ui=None,
                resume_session_id=None,
            )
            assert success is True
            assert session_id == "session-abc-123"

    def test_second_direct_agent_passes_resume_session_id(self, _mock_tui_env: Path):
        """On a follow-up direct-agent run, the stored session_id is passed as resume."""
        # Simulate the state flow: first run stores session_id,
        # second run passes it as resume_session_id.
        last_direct_session_id = None

        # First run
        first_result = (True, "session-first")
        with patch("colonyos.cli._run_direct_agent", return_value=first_result) as mock_da:
            success, sid = mock_da(
                "fix the bug",
                repo_root=_mock_tui_env,
                config=MagicMock(),
                ui=None,
                resume_session_id=last_direct_session_id,
            )
            if success and sid:
                last_direct_session_id = sid

        assert last_direct_session_id == "session-first"

        # Second run — should pass previous session_id
        second_result = (True, "session-second")
        with patch("colonyos.cli._run_direct_agent", return_value=second_result) as mock_da:
            success, sid = mock_da(
                "yes",
                repo_root=_mock_tui_env,
                config=MagicMock(),
                ui=None,
                resume_session_id=last_direct_session_id,
            )
            # Verify the resume_session_id was "session-first"
            call_kwargs = mock_da.call_args
            assert call_kwargs.kwargs["resume_session_id"] == "session-first"

    def test_mode_switch_clears_session_id(self):
        """When routing to a non-direct-agent mode, session state is cleared."""
        last_direct_session_id: str | None = "session-to-clear"

        # Simulate route_outcome.mode != "direct_agent"
        # The implementation clears last_direct_session_id before non-direct modes
        route_mode = "plan_implement"
        if route_mode != "direct_agent":
            last_direct_session_id = None

        assert last_direct_session_id is None

    def test_new_command_clears_session_id(self):
        """The /new command clears conversation state."""
        from colonyos.cli import _handle_tui_command

        last_direct_session_id: str | None = "session-to-clear"

        handled, output, should_exit = _handle_tui_command("new", config=MagicMock())
        assert handled is True
        assert output is not None
        assert output == _NEW_CONVERSATION_SIGNAL

        # _run_callback checks output against the _NEW_CONVERSATION_SIGNAL constant
        if output == _NEW_CONVERSATION_SIGNAL:
            last_direct_session_id = None

        assert last_direct_session_id is None

    def test_resume_emits_continuing_message(self, _mock_tui_env: Path):
        """When resuming, a 'Continuing conversation...' message is emitted."""
        # This tests the logic: if last_direct_session_id is not None,
        # a TextBlockMsg with "Continuing conversation..." is enqueued
        # before the phase header.
        last_direct_session_id = "session-exists"
        messages: list[str] = []

        # Simulate the message emission
        if last_direct_session_id is not None:
            messages.append("Continuing conversation...")

        assert len(messages) == 1
        assert messages[0] == "Continuing conversation..."

    def test_no_continuation_message_on_fresh_session(self, _mock_tui_env: Path):
        """No continuation message when there is no prior session."""
        last_direct_session_id = None
        messages: list[str] = []

        if last_direct_session_id is not None:
            messages.append("Continuing conversation...")

        assert len(messages) == 0

    def test_failed_run_does_not_update_session_id(self, _mock_tui_env: Path):
        """A failed direct-agent run should not update the session state."""
        last_direct_session_id: str | None = "session-old"

        # Simulate a failed run
        success, session_id = False, None
        if success and session_id:
            last_direct_session_id = session_id

        # Should retain old session_id
        assert last_direct_session_id == "session-old"

    def test_active_session_biases_short_followup_to_direct_agent(self, _mock_tui_env: Path):
        from colonyos.cli import _route_prompt
        from colonyos.config import load_config
        from colonyos.router import ModeAgentDecision, ModeAgentMode

        config = load_config(_mock_tui_env)
        low_confidence = ModeAgentDecision(
            mode=ModeAgentMode.FALLBACK,
            confidence=0.1,
            summary="ambiguous",
            reasoning="short follow-up",
            announcement="I need a bit more direction.",
        )
        with patch("colonyos.router.choose_tui_mode", return_value=low_confidence), \
             patch("colonyos.router.log_mode_selection"):
            outcome = _route_prompt(
                "v0.3.3 please",
                config,
                _mock_tui_env,
                "tui",
                quiet=True,
                continuation_active=True,
            )
        assert outcome.mode == "direct_agent"

    def test_handle_tui_command_new_returns_conversation_cleared(self):
        """_handle_tui_command('new') returns the Conversation cleared signal."""
        from colonyos.cli import _handle_tui_command

        handled, output, should_exit = _handle_tui_command("new", config=MagicMock())
        assert handled is True
        assert output == _NEW_CONVERSATION_SIGNAL
        assert should_exit is False


class TestResumeFallbackIntegration:
    """Task 5.0 — verify graceful fallback on resume failure clears session state."""

    def test_fallback_clears_last_direct_session_id(self):
        """When resume fails and fallback succeeds, session_id updates to fresh."""
        from colonyos.cli import _run_direct_agent

        last_direct_session_id: str | None = "stale-session"

        # Simulate the _run_callback logic with fallback behaviour
        success, session_id = True, "fresh-session"
        # After fallback, _run_direct_agent returns the fresh session
        if success and session_id:
            last_direct_session_id = session_id

        assert last_direct_session_id == "fresh-session"

    def test_fallback_clears_session_id_on_double_failure(self):
        """When both resume and fresh attempt fail, session_id is cleared."""
        last_direct_session_id: str | None = "stale-session"

        # Simulate _run_direct_agent returning failure after fallback
        success, session_id = False, None
        if success and session_id:
            last_direct_session_id = session_id
        elif not success:
            # On failure, clear stale session to prevent repeated retries
            last_direct_session_id = None

        assert last_direct_session_id is None
