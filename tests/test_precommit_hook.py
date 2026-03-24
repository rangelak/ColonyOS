"""Tests for the targeted pre-commit pytest selector."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from run_precommit_tests import (
    _collect_targets,
    _python_candidates,
    _select_python,
    _staged_files,
    _targets_for_path,
    main,
)


def test_targets_for_tui_module_include_tui_suite_and_cli() -> None:
    with (
        patch("run_precommit_tests._tui_suite", return_value=["tests/tui/test_app.py"]),
        patch("run_precommit_tests._existing", side_effect=lambda path: path),
    ):
        targets = _targets_for_path(Path("src/colonyos/tui/app.py"))

    assert "tests/tui/test_app.py" in targets
    assert "tests/test_cli.py" in targets


def test_targets_for_precommit_script_include_dedicated_tests() -> None:
    with patch("run_precommit_tests._existing", side_effect=lambda path: path):
        targets = _targets_for_path(Path("run_precommit_tests.py"))

    assert targets == {"tests/test_precommit_hook.py"}


def test_collect_targets_deduplicates_results() -> None:
    with patch(
        "run_precommit_tests._targets_for_path",
        side_effect=[
            {"tests/test_cli.py", "tests/tui/test_app.py"},
            {"tests/test_cli.py"},
        ],
    ):
        targets = _collect_targets([Path("src/colonyos/cli.py"), Path("src/colonyos/tui/app.py")])

    assert targets == ["tests/test_cli.py", "tests/tui/test_app.py"]


def test_main_uses_current_python_for_pytest(monkeypatch) -> None:
    monkeypatch.setattr("run_precommit_tests._staged_files", lambda: [Path("run_precommit_tests.py")])
    monkeypatch.setattr(
        "run_precommit_tests._collect_targets",
        lambda paths: ["tests/test_precommit_hook.py"],
    )
    monkeypatch.setattr("run_precommit_tests._select_python", lambda: "/usr/bin/python3")

    completed = MagicMock(returncode=0)
    with patch("run_precommit_tests.subprocess.run", return_value=completed) as mock_run:
        exit_code = main()

    assert exit_code == 0
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["/usr/bin/python3", "-m", "pytest"]


def test_python_candidates_prefer_repo_venv(monkeypatch) -> None:
    monkeypatch.setattr("run_precommit_tests.sys.executable", "/usr/bin/python3")

    def fake_exists(path: Path) -> bool:
        return str(path).endswith("/.venv/bin/python")

    with (
        patch("run_precommit_tests.REPO_ROOT", Path("/repo")),
        patch("pathlib.Path.exists", fake_exists),
    ):
        candidates = _python_candidates()

    assert candidates[0].endswith(".venv/bin/python")
    assert candidates[1] == "/usr/bin/python3"


def test_select_python_returns_none_when_pytest_missing() -> None:
    failed = MagicMock(returncode=1)
    with (
        patch("run_precommit_tests._python_candidates", return_value=["/a/python", "/b/python"]),
        patch("run_precommit_tests.subprocess.run", return_value=failed),
    ):
        python = _select_python()

    assert python is None


def test_staged_files_raises_runtime_error_with_git_context() -> None:
    error = subprocess.CalledProcessError(
        1,
        ["git", "diff"],
        stderr="fatal: not a git repository",
    )
    with patch("run_precommit_tests.subprocess.run", side_effect=error):
        with patch("run_precommit_tests.REPO_ROOT", Path("/repo")):
            with pytest.raises(RuntimeError, match="failed to inspect staged files"):
                _staged_files()


def test_main_returns_error_when_staged_file_lookup_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "run_precommit_tests._staged_files",
        lambda: (_ for _ in ()).throw(RuntimeError("pre-commit pytest: boom")),
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "pre-commit pytest: boom" in captured.err
