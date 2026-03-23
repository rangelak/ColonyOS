#!/usr/bin/env python3
"""Run targeted pytest selections for staged files.

This hook is intentionally conservative about runtime. It prefers a small,
relevant test slice over running the full suite on every commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _staged_files() -> list[Path]:
    """Return staged paths relative to the repo root."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _existing(path: str) -> str | None:
    """Return the relative path if it exists in the repo."""
    candidate = REPO_ROOT / path
    return path if candidate.exists() else None


def _tui_suite() -> list[str]:
    """Return the focused TUI suite."""
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests" / "tui").glob("test_*.py")
    )


def _python_candidates() -> list[str]:
    """Return likely Python executables in preference order."""
    candidates: list[str] = []
    repo_python = REPO_ROOT / ".venv" / "bin" / "python"
    if repo_python.exists():
        candidates.append(str(repo_python))
    candidates.append(sys.executable)
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _select_python() -> str | None:
    """Pick a Python interpreter that can import pytest."""
    for candidate in _python_candidates():
        result = subprocess.run(
            [candidate, "-c", "import pytest"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    return None


def _targets_for_path(path: Path) -> set[str]:
    """Infer the most relevant pytest targets for a staged path."""
    targets: set[str] = set()
    path_str = path.as_posix()

    if path_str.startswith("tests/") and path.suffix == ".py":
        targets.add(path_str)
        return targets

    if path_str == "run_precommit_tests.py":
        if target := _existing("tests/test_precommit_hook.py"):
            targets.add(target)
        return targets

    if path_str.startswith("src/colonyos/tui/"):
        targets.update(_tui_suite())
        if cli_test := _existing("tests/test_cli.py"):
            targets.add(cli_test)
        return targets

    if path_str == "src/colonyos/cli.py":
        if cli_test := _existing("tests/test_cli.py"):
            targets.add(cli_test)
        targets.update(_tui_suite())
        return targets

    if path_str == "src/colonyos/config.py":
        if target := _existing("tests/test_config.py"):
            targets.add(target)
        return targets

    if path_str == "src/colonyos/router.py":
        if target := _existing("tests/test_router.py"):
            targets.add(target)
        return targets

    if path_str == "src/colonyos/orchestrator.py":
        if target := _existing("tests/test_orchestrator.py"):
            targets.add(target)
        return targets

    if path_str == "src/colonyos/slack.py":
        if target := _existing("tests/test_slack.py"):
            targets.add(target)
        return targets

    if path_str.startswith("src/colonyos/") and path.suffix == ".py":
        stem = path.stem
        if target := _existing(f"tests/test_{stem}.py"):
            targets.add(target)

    if path_str in {".pre-commit-config.yaml", "pyproject.toml"}:
        if cli_test := _existing("tests/test_cli.py"):
            targets.add(cli_test)
        targets.update(_tui_suite())

    return targets


def _collect_targets(paths: list[Path]) -> list[str]:
    """Collect unique pytest targets for all staged paths."""
    targets: set[str] = set()
    for path in paths:
        targets.update(_targets_for_path(path))
    return sorted(targets)


def main() -> int:
    """Run targeted tests for staged files, or skip if nothing relevant changed."""
    staged = _staged_files()
    if not staged:
        print("pre-commit pytest: no staged files, skipping")
        return 0

    targets = _collect_targets(staged)
    if not targets:
        print("pre-commit pytest: no mapped tests for staged files, skipping")
        return 0

    print("pre-commit pytest targets:")
    for target in targets:
        print(f"  - {target}")

    python = _select_python()
    if python is None:
        print(
            "pre-commit pytest: could not find a Python interpreter with pytest installed. "
            "Install dev dependencies (for example `pip install -e \".[dev]\"`).",
            file=sys.stderr,
        )
        return 1

    cmd = [python, "-m", "pytest", "--tb=short", "-q", *targets]
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
