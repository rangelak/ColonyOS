# Tasks: Refactor `daemon.py` into `daemon/` Package (Recovery v7)

## Context

This is the 7th attempt at this refactoring. Previous 6 attempts failed because they tried to extract Daemon methods into standalone submodule functions, which broke `patch.object(daemon_instance, ...)` mock targets in the 3,225-line test file.

**Key insight this time:** Tests use `patch.object` (instance-bound), NOT `patch("colonyos.daemon.<method>")`. Therefore:
- Standalone classes (zero `self.*` coupling) can be freely extracted
- Daemon methods must stay on `self` — use **mixins** so methods remain on the Daemon instance
- Zero test modifications required

**Critical rule:** Run `python -m pytest tests/test_daemon.py -x -q` after every extraction step. If tests fail, revert and debug before proceeding.

## Relevant Files

- `src/colonyos/daemon.py` - The 2,655-line monolith to be refactored (deleted, replaced by package)
- `src/colonyos/daemon/__init__.py` - New: Daemon class coordinator + re-exports (~2,100 lines)
- `src/colonyos/daemon/_ui.py` - New: Standalone UI classes and DaemonError (~220 lines)
- `src/colonyos/daemon/_watchdog.py` - New: _WatchdogMixin with watchdog methods (~140 lines)
- `src/colonyos/daemon/_resilience.py` - New: _ResilienceMixin with recovery methods (~200 lines)
- `tests/test_daemon.py` - Existing test file (3,225 lines) — NO MODIFICATIONS
- `src/colonyos/cli.py` - Imports `Daemon, DaemonError` at line 4865 — NO MODIFICATIONS

## Tasks

- [x] 1.0 Convert `daemon.py` to `daemon/` package and extract standalone classes
  depends_on: []
  - [x] 1.1 Verify all tests pass on the current monolith (`python -m pytest tests/test_daemon.py -x -q`)
  - [x] 1.2 Create `src/colonyos/daemon/` directory
  - [x] 1.3 Create `src/colonyos/daemon/_ui.py` containing `DaemonError`, `_CombinedUI`, and `_DaemonMonitorEventUI` — copy these classes verbatim (lines 69-290 of `daemon.py`). Include only the imports these classes need: `logging`, `threading`, `sys`, `typing.Any`, and `from colonyos.tui.monitor_protocol import encode_monitor_event`
  - [x] 1.4 Create `src/colonyos/daemon/__init__.py` by copying the entire `daemon.py` content, then: (a) remove the three extracted class definitions, (b) add `from colonyos.daemon._ui import DaemonError, _CombinedUI, _DaemonMonitorEventUI` at the top, (c) keep all module-level imports and constants
  - [x] 1.5 Delete `src/colonyos/daemon.py` (the original file — now replaced by the package)
  - [x] 1.6 Run `python -m pytest tests/test_daemon.py -x -q` — all 71 tests must pass with zero modifications
  - [x] 1.7 Verify `from colonyos.daemon import Daemon, DaemonError` works (matches `cli.py` usage)
  - [x] 1.8 Commit: "refactor(daemon): convert to package, extract standalone UI classes"

- [ ] 2.0 Extract watchdog methods into `_WatchdogMixin`
  depends_on: [1.0]
  - [ ] 2.1 Create `src/colonyos/daemon/_watchdog.py` with a `_WatchdogMixin` class containing these methods moved verbatim from `__init__.py`:
    - `_start_watchdog_thread` (line ~1720)
    - `_watchdog_loop` (line ~1730)
    - `_watchdog_check` (line ~1739)
    - `_watchdog_recover` (line ~1790)
    The mixin class needs these imports: `logging`, `sys`, `time`, `threading`, `typing.Any`, `from colonyos.agent import active_phase_controller_count, request_active_phase_cancel`, `from colonyos.cancellation import request_cancel`, `from colonyos.models import QueueItemStatus`, `from colonyos.tui.monitor_protocol import encode_monitor_event`
  - [ ] 2.2 In `daemon/__init__.py`: (a) add `from colonyos.daemon._watchdog import _WatchdogMixin`, (b) change `class Daemon:` to `class Daemon(_WatchdogMixin):`, (c) remove the 4 watchdog method bodies (keep only in mixin)
  - [ ] 2.3 Run `python -m pytest tests/test_daemon.py -x -q` — all tests must pass
  - [ ] 2.4 Commit: "refactor(daemon): extract watchdog methods into _WatchdogMixin"

- [ ] 3.0 Extract resilience/recovery methods into `_ResilienceMixin`
  depends_on: [2.0]
  - [ ] 3.1 Create `src/colonyos/daemon/_resilience.py` with a `_ResilienceMixin` class containing these methods moved verbatim from `__init__.py`:
    - `_recover_from_crash` (line ~1392)
    - `_preexec_worktree_state` (line ~1443)
    - `_recover_dirty_worktree_preemptive` (line ~1460)
    - `_should_auto_recover_dirty_worktree` (line ~1497)
    - `_should_auto_recover_existing_branch` (line ~1505, @staticmethod)
    - `_recover_existing_branch_and_retry` (line ~1513)
    - `_recover_dirty_worktree_and_retry` (line ~1541)
    The mixin class needs these imports: `logging`, `subprocess`, `typing.Any`, `from pathlib import Path`, `from colonyos.models import PreflightError, QueueItem, QueueItemStatus`
    Note: Methods use lazy imports (`from colonyos.recovery import ...`, `from colonyos.orchestrator import ...`) — keep those as-is inside the method bodies
  - [ ] 3.2 In `daemon/__init__.py`: (a) add `from colonyos.daemon._resilience import _ResilienceMixin`, (b) change `class Daemon(_WatchdogMixin):` to `class Daemon(_WatchdogMixin, _ResilienceMixin):`, (c) remove the 7 resilience method bodies
  - [ ] 3.3 Run `python -m pytest tests/test_daemon.py -x -q` — all tests must pass
  - [ ] 3.4 Commit: "refactor(daemon): extract recovery methods into _ResilienceMixin"

- [ ] 4.0 Extract helper/formatting methods into `_HelpersMixin`
  depends_on: [3.0]
  - [ ] 4.1 Create `src/colonyos/daemon/_helpers.py` with a `_HelpersMixin` class containing these methods moved verbatim from `__init__.py`:
    - `_failure_summary` (line ~2618)
    - `_failure_guidance` (line ~2623)
    - `_format_item_error` (line ~2651)
    - `_budget_cap_label` (line ~2469)
    - `_spent_summary` (line ~2475)
    - `_record_runtime_incident` (line ~2482)
    - `_maybe_record_budget_incident` (line ~2504)
    - `_budget_exhaustion_guidance` (line ~2527)
    - `_is_systemic_failure` (line ~2537)
    - `_warn_all_mode_safety` (line ~1857, @staticmethod)
    These are pure-ish functions that read `self.*` state but don't mutate it (except `_record_runtime_incident` which writes files). They have no call dependencies on other Daemon methods being extracted in the same step.
    Imports needed: `logging`, `from pathlib import Path`, `from datetime import datetime, timezone`, `typing.Any`
  - [ ] 4.2 In `daemon/__init__.py`: (a) add `from colonyos.daemon._helpers import _HelpersMixin`, (b) add `_HelpersMixin` to `Daemon`'s inheritance, (c) remove the helper method bodies
  - [ ] 4.3 Run `python -m pytest tests/test_daemon.py -x -q` — all tests must pass
  - [ ] 4.4 Commit: "refactor(daemon): extract helper/formatting methods into _HelpersMixin"

- [ ] 5.0 Final verification and cleanup
  depends_on: [4.0]
  - [ ] 5.1 Run the full test suite: `python -m pytest tests/ -x -q` (not just daemon tests)
  - [ ] 5.2 Verify import backward compatibility: `python -c "from colonyos.daemon import Daemon, DaemonError; print('OK')"`
  - [ ] 5.3 Verify no circular imports: `python -c "import colonyos.daemon; print('OK')"`
  - [ ] 5.4 Count lines in `daemon/__init__.py` — should be ~2,100 or less (down from 2,655)
  - [ ] 5.5 Verify all new files exist: `_ui.py`, `_watchdog.py`, `_resilience.py`, `_helpers.py`
  - [ ] 5.6 Ensure no commented-out code or TODOs in new files
  - [ ] 5.7 Commit any final cleanup: "refactor(daemon): final cleanup of package structure"

## Dependency Graph

```
1.0 (package skeleton + standalone classes)
 └─► 2.0 (watchdog mixin)
      └─► 3.0 (resilience mixin)
           └─► 4.0 (helpers mixin)
                └─► 5.0 (verification)
```

All tasks are strictly sequential — each depends on the previous one passing tests. This is intentional: after 6 failures, parallelism adds risk with no benefit on a single-file refactor.

## Risk Mitigations

1. **Mock target safety**: Mixins keep methods on `self` — `patch.object(daemon_instance, "_method")` targets are unchanged
2. **No test modifications**: If any task requires changing `tests/test_daemon.py`, STOP and re-evaluate the approach
3. **Atomic commits**: Each task is one commit. If task N fails, revert to task N-1's commit
4. **Lazy imports preserved**: Methods that use `from colonyos.xyz import ...` inside the method body keep that pattern in the mixin
5. **No circular imports**: Mixins import only from stdlib and `colonyos.*` (never from `daemon/`)
6. **Re-exports**: `daemon/__init__.py` re-exports all public names so external imports are unchanged
