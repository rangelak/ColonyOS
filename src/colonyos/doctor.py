"""Prerequisite checks for ColonyOS.

Extracted into its own module to avoid circular imports between
``cli.py`` and ``init.py``.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


def detect_install_method() -> tuple[str, str]:
    """Detect how ColonyOS was installed and return (method, upgrade_hint).

    Returns one of:
    - ("homebrew", "brew upgrade colonyos")
    - ("pipx", "pipx upgrade colonyos")
    - ("pip", "pip install --upgrade colonyos")
    """
    exe_path = sys.executable

    # Homebrew installs Python inside its Cellar directory
    if "/Cellar/" in exe_path:
        return ("homebrew", "brew upgrade colonyos")

    # pipx installs packages in its own venvs directory
    if "/pipx/venvs/" in exe_path:
        return ("pipx", "pipx upgrade colonyos")

    # Fallback: assume pip
    return ("pip", "pip install --upgrade colonyos")


def run_doctor_checks(repo_root: Path) -> list[tuple[str, bool, str]]:
    """Run all prerequisite checks and return a list of (name, passed, fix_hint).

    This is extracted as a reusable function so both ``colonyos doctor`` and
    ``colonyos init`` can call it without circular imports.
    """
    from colonyos import __version__

    results: list[tuple[str, bool, str]] = []

    # Detect install method for accurate upgrade instructions
    install_method, upgrade_hint = detect_install_method()

    # 0. ColonyOS version — flag degraded state when using fallback version
    version_ok = "dev" not in __version__ and __version__ != "0.0.0"
    results.append((
        f"ColonyOS v{__version__}",
        version_ok,
        "Version appears to be a development fallback. "
        f"Reinstall with: {upgrade_hint}" if not version_ok else "",
    ))

    # 0b. Install method (informational — always passes)
    method_labels = {
        "homebrew": "Homebrew",
        "pipx": "pipx",
        "pip": "pip",
    }
    results.append((
        f"Install method: {method_labels.get(install_method, install_method)}",
        True,
        f"Upgrade with: {upgrade_hint}",
    ))

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

    # 6. Slack tokens (soft check — only when slack is enabled)
    try:
        from colonyos.config import load_config

        slack_config = load_config(repo_root).slack
    except Exception:
        slack_config = None

    if slack_config is not None and slack_config.enabled:
        bot_token = os.environ.get("COLONYOS_SLACK_BOT_TOKEN", "").strip()
        app_token = os.environ.get("COLONYOS_SLACK_APP_TOKEN", "").strip()
        if bot_token and app_token:
            results.append(("Slack tokens", True, ""))
        else:
            missing: list[str] = []
            if not bot_token:
                missing.append("COLONYOS_SLACK_BOT_TOKEN")
            if not app_token:
                missing.append("COLONYOS_SLACK_APP_TOKEN")
            results.append((
                "Slack tokens",
                False,
                f"Missing environment variables: {', '.join(missing)}. "
                "Set them before running `colonyos watch`.",
            ))

        try:
            importlib.import_module("slack_bolt")
            importlib.import_module("slack_bolt.adapter.socket_mode")
            results.append(("Slack dependencies", True, ""))
        except Exception as exc:
            results.append((
                "Slack dependencies",
                False,
                f"Slack SDK import failed ({exc.__class__.__name__}). "
                "Reinstall with `pip install 'colonyos[slack]'` and prefer "
                "Python 3.11-3.13 for Slack-enabled deployments.",
            ))

    return results
