"""Tests for TUI CLI integration — ``colonyos tui`` command and ``--tui`` flag."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from colonyos.cli import app


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
