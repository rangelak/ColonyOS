"""Prerequisite checks for ColonyOS.

Extracted into its own module to avoid circular imports between
``cli.py`` and ``init.py``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_doctor_checks(repo_root: Path) -> list[tuple[str, bool, str]]:
    """Run all prerequisite checks and return a list of (name, passed, fix_hint).

    This is extracted as a reusable function so both ``colonyos doctor`` and
    ``colonyos init`` can call it without circular imports.
    """
    results: list[tuple[str, bool, str]] = []

    # 1. Python >= 3.11
    py_ok = sys.version_info.major >= 3 and sys.version_info.minor >= 11
    results.append((
        "Python ≥ 3.11",
        py_ok,
        f"Current: {sys.version_info.major}.{sys.version_info.minor}. "
        "Install Python 3.11+: https://www.python.org/downloads/"
    ))

    # 2. claude CLI reachable
    try:
        subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        results.append(("Claude Code CLI", True, ""))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append((
            "Claude Code CLI",
            False,
            "Install Claude Code: npm install -g @anthropic-ai/claude-code",
        ))

    # 3. git reachable
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        results.append(("Git", True, ""))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append(("Git", False, "Install Git: https://git-scm.com/downloads"))

    # 4. gh auth status
    try:
        gh = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        gh_ok = gh.returncode == 0
        results.append((
            "GitHub CLI auth",
            gh_ok,
            "Run: gh auth login (install: https://cli.github.com/)" if not gh_ok else "",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append((
            "GitHub CLI auth",
            False,
            "Install GitHub CLI: https://cli.github.com/ then run: gh auth login",
        ))

    # 5. Config file (soft check)
    config_path = repo_root / ".colonyos" / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            yaml.safe_load(config_path.read_text(encoding="utf-8"))
            results.append(("ColonyOS config", True, ""))
        except Exception:
            results.append((
                "ColonyOS config",
                False,
                f"Config file at {config_path} is invalid YAML. "
                "Run `colonyos init` to regenerate.",
            ))
    else:
        results.append((
            "ColonyOS config",
            False,
            "No config found. Run `colonyos init` to set up.",
        ))

    return results
