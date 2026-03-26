"""Tests for TUI package setup: optional dependency guard and styles."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


class TestLazyImportGuard:
    """Verify the tui package raises a clear error when deps are missing."""

    def test_import_succeeds_when_deps_available(self, require_tui: None) -> None:
        """Package imports cleanly when textual and janus are installed."""
        import colonyos.tui  # noqa: F401

    def test_import_fails_without_textual(self) -> None:
        """ImportError with actionable message when textual is missing."""
        # Remove the cached module so re-import triggers the guard
        mods_to_remove = [k for k in sys.modules if k.startswith("colonyos.tui")]
        saved = {}
        for k in mods_to_remove:
            saved[k] = sys.modules.pop(k)

        orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "textual":
                raise ImportError("No module named 'textual'")
            return orig_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                with pytest.raises(ImportError, match="pip install colonyos\\[tui\\]"):
                    importlib.import_module("colonyos.tui")
        finally:
            # Restore cached modules
            for k in [key for key in sys.modules if key.startswith("colonyos.tui")]:
                sys.modules.pop(k, None)
            sys.modules.update(saved)

    def test_import_fails_without_janus(self) -> None:
        """ImportError with actionable message when janus is missing."""
        mods_to_remove = [k for k in sys.modules if k.startswith("colonyos.tui")]
        saved = {}
        for k in mods_to_remove:
            saved[k] = sys.modules.pop(k)

        orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "janus":
                raise ImportError("No module named 'janus'")
            return orig_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                with pytest.raises(ImportError, match="pip install colonyos\\[tui\\]"):
                    importlib.import_module("colonyos.tui")
        finally:
            for k in [key for key in sys.modules if key.startswith("colonyos.tui")]:
                sys.modules.pop(k, None)
            sys.modules.update(saved)


class TestStyles:
    """Verify styles module exports expected constants."""

    def test_tool_colors_match_ui_module(self) -> None:
        """TOOL_COLORS should mirror TOOL_STYLE from ui.py."""
        from colonyos.tui.styles import TOOL_COLORS
        from colonyos.ui import TOOL_STYLE

        for tool, color in TOOL_STYLE.items():
            assert TOOL_COLORS.get(tool) == color, (
                f"TOOL_COLORS[{tool!r}] = {TOOL_COLORS.get(tool)!r}, "
                f"expected {color!r} from TOOL_STYLE"
            )

    def test_app_css_is_nonempty_string(self) -> None:
        from colonyos.tui.styles import APP_CSS

        assert isinstance(APP_CSS, str)
        assert len(APP_CSS) > 50

    def test_spinner_frames_defined(self) -> None:
        from colonyos.tui.styles import SPINNER_FRAMES

        assert len(SPINNER_FRAMES) >= 8

    def test_semantic_colors_defined(self) -> None:
        from colonyos.tui.styles import (
            COLOR_SUCCESS,
            COLOR_ERROR,
            COLOR_WARNING,
            COLOR_ACCENT,
        )

        assert COLOR_SUCCESS == "green"
        assert COLOR_ERROR == "red"
        assert COLOR_WARNING == "yellow"
        assert isinstance(COLOR_ACCENT, str)


class TestPackageStructure:
    """Verify the package directory layout."""

    def test_widgets_package_importable(self) -> None:
        import colonyos.tui.widgets  # noqa: F401

    def test_styles_module_importable(self) -> None:
        import colonyos.tui.styles  # noqa: F401
