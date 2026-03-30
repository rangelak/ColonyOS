"""ColonyOS CLI package.

Public entry point: ``colonyos.cli:app`` (unchanged from the monolith era).

This ``__init__.py`` re-exports every symbol that external code or tests
import from ``colonyos.cli`` so that existing import paths keep working
while the implementation is split across focused sub-modules.

During the migration (tasks 1–5), un-extracted symbols are re-exported from
``_legacy.py`` (the original monolith, renamed).  As each command module is
extracted, its symbols move from ``_legacy`` to the new sub-module.  Task 6
deletes ``_legacy.py`` once it is empty.
"""

from __future__ import annotations

# --- Foundation: newly extracted modules -----------------------------------
# These are importable directly (e.g. ``from colonyos.cli._helpers import ...``)
# and also re-exported here for convenience.
from colonyos.cli._helpers import (
    _announce_mode_cli as _announce_mode_cli,
    _current_branch_name as _current_branch_name,
    _dirty_recovery_help as _dirty_recovery_help,
    _find_repo_root as _find_repo_root,
    _interactive_stdio as _interactive_stdio,
    _load_dotenv as _load_dotenv,
    _tui_available as _tui_available,
)

# --- Legacy re-exports (removed as modules are extracted) ------------------
# Public names (no leading underscore) are picked up by the wildcard import.
# This includes ``app`` (the Click group with all commands registered),
# ``RouteOutcome``, ``REPL_HISTORY_PATH``, ``run_pipeline_for_queue_item``, etc.
from colonyos.cli._legacy import *  # noqa: F401, F403

# Private symbols must be imported explicitly because ``import *`` skips
# names starting with ``_``.  This list covers every ``_``-prefixed name
# imported by test files or ``src/colonyos/daemon.py``.
from colonyos.cli._legacy import (  # noqa: F401, F811
    # routing / agent helpers
    _route_prompt as _route_prompt,
    _handle_routed_query as _handle_routed_query,
    _run_direct_agent as _run_direct_agent,
    _run_cleanup_loop as _run_cleanup_loop,
    _run_review_only_flow as _run_review_only_flow,
    # auto / loop state
    _compute_elapsed_hours as _compute_elapsed_hours,
    _save_loop_state as _save_loop_state,
    _load_latest_loop_state as _load_latest_loop_state,
    _ensure_on_main as _ensure_on_main,
    # queue state
    _save_queue_state as _save_queue_state,
    _load_queue_state as _load_queue_state,
    _is_nogo_verdict as _is_nogo_verdict,
    # run command helpers
    _resolve_latest_prd_path as _resolve_latest_prd_path,
    # display
    _print_run_summary as _print_run_summary,
    _print_review_summary as _print_review_summary,
    _print_queue_summary as _print_queue_summary,
    # REPL
    _run_repl as _run_repl,
    # TUI
    _launch_tui as _launch_tui,
    _NEW_CONVERSATION_SIGNAL as _NEW_CONVERSATION_SIGNAL,
    _SAFE_TUI_COMMANDS as _SAFE_TUI_COMMANDS,
    _handle_tui_command as _handle_tui_command,
    _AUTO_COMMAND_SIGNAL as _AUTO_COMMAND_SIGNAL,
    # welcome banner (needed by mock.patch targets in tests)
    _show_welcome as _show_welcome,
)

__all__ = [
    "app",
    "RouteOutcome",
    "run_pipeline_for_queue_item",
    # helpers
    "_find_repo_root",
    "_tui_available",
    "_interactive_stdio",
    "_load_dotenv",
    "_current_branch_name",
    "_announce_mode_cli",
    "_dirty_recovery_help",
]
