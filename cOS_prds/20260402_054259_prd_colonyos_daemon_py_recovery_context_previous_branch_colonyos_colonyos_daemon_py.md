# PRD: Refactor `daemon.py` into `daemon/` Package (Recovery Plan v7)

## Introduction/Overview

The `src/colonyos/daemon.py` file is a 2,655-line monolith containing 112 functions across one `Daemon` class plus two standalone UI classes. This PRD defines a **radically conservative** refactoring strategy to convert it into a `daemon/` package — informed by 6 prior failed attempts and unanimous expert consensus that ambitious method extraction is too risky.

**Why this plan is different:** Previous attempts failed by trying to move Daemon methods into submodule functions, which broke `patch.object(daemon_instance, ...)` mock targets in the 3,225-line test file. This plan uses a two-phase approach:
1. **Phase 1 (this PR):** Extract only standalone classes with zero `self.*` coupling, plus convert to package structure.
2. **Phase 2 (this PR, if Phase 1 passes):** Use **mixins** to split Daemon method groups across files while keeping all methods on `self` — the only pattern that preserves mock targets.

## Goals

1. Convert `daemon.py` to a `daemon/` package without breaking any imports or tests
2. Extract ~200 lines of standalone classes (`_CombinedUI`, `_DaemonMonitorEventUI`, `DaemonError`) into dedicated submodules
3. Extract ~300 lines of watchdog and recovery methods via mixins (methods remain on `self`)
4. Reduce the main `daemon/__init__.py` from 2,655 lines to ~2,100 lines
5. Establish the package structure for future incremental extractions
6. All 71 daemon tests must pass at every intermediate commit

## User Stories

1. **As a developer**, I can navigate `daemon/` submodules to find related code (UI, watchdog, recovery) without scrolling through a 2,655-line file.
2. **As a contributor**, I can modify watchdog behavior by editing `daemon/_watchdog.py` without merge conflicts on the main coordinator logic.
3. **As a test author**, I can continue using `patch.object(daemon_instance, ...)` without changing any mock targets because methods remain on `self` via mixins.
4. **As a CI consumer**, `from colonyos.daemon import Daemon, DaemonError` continues to work unchanged.

## Functional Requirements

1. **FR-1**: `daemon.py` becomes `daemon/__init__.py` with identical behavior
2. **FR-2**: `DaemonError`, `_CombinedUI`, `_DaemonMonitorEventUI` move to `daemon/_ui.py` and are re-exported from `daemon/__init__.py`
3. **FR-3**: Watchdog methods (`_start_watchdog_thread`, `_watchdog_loop`, `_watchdog_check`, `_watchdog_recover`) move to `daemon/_watchdog.py` as a `_WatchdogMixin` class
4. **FR-4**: Recovery methods (`_recover_from_crash`, `_preexec_worktree_state`, `_recover_dirty_worktree_preemptive`, `_should_auto_recover_dirty_worktree`, `_should_auto_recover_existing_branch`, `_recover_existing_branch_and_retry`, `_recover_dirty_worktree_and_retry`) move to `daemon/_resilience.py` as a `_ResilienceMixin` class
5. **FR-5**: `Daemon` class inherits from `_WatchdogMixin` and `_ResilienceMixin`
6. **FR-6**: `from colonyos.daemon import Daemon, DaemonError` works unchanged (backward compatibility)
7. **FR-7**: All existing tests pass without modification to mock targets or test structure
8. **FR-8**: No circular imports between submodules

## Non-Goals

- **Not extracting notification methods** — 17 methods with heavy `self.*` coupling to Slack state, daily threads, and locks. Identified as the failure point in attempt #6. Deferred to a follow-up PR.
- **Not extracting scheduling methods** — `_poll_github_issues`, `_schedule_ceo`, etc. have moderate coupling. Deferred.
- **Not extracting execution methods** — `_try_execute_next`, `_execute_item` are the most coupled methods. Deferred.
- **Not splitting `tests/test_daemon.py`** — 6/7 personas agreed: tests are the regression oracle, split them in a separate effort.
- **Not restructuring Daemon state** — The 35+ instance variables in `__init__` are deeply interleaved. Architectural redesign is a separate effort.

## Technical Considerations

### Why Mixins Work (and Functions Don't)

Tests use `patch.object(daemon_instance, "_method_name")` extensively. When a method is defined on a mixin class and inherited by `Daemon`, the method is still on `self` — `patch.object` targets are unchanged. When a method is moved to a submodule function, the mock target changes (e.g., `colonyos.daemon._notifications._post_slack_message`) and every test that patches it must be updated.

### Existing Import Surface

Only one external import (from `src/colonyos/cli.py:4865`):
```python
from colonyos.daemon import Daemon, DaemonError
```

Tests import:
```python
from colonyos.daemon import Daemon, DaemonError, _CombinedUI, _DaemonMonitorEventUI
```

All re-exported from `daemon/__init__.py`.

### Module-Level Patches in Tests

There is exactly one module-level patch: `patch("colonyos.daemon.RepoRuntimeGuard.acquire", ...)`. Since `RepoRuntimeGuard` is imported at the top of the current `daemon.py` and will remain imported in `daemon/__init__.py`, this patch target does not change.

### Mixin Import Rules (No Circular Imports)

- Mixins import only from stdlib, external packages, and `colonyos.*` modules (never from `daemon/`)
- `daemon/__init__.py` imports mixins and defines `class Daemon(_WatchdogMixin, _ResilienceMixin)`
- Mixins use `self.*` for all Daemon state access — no explicit type annotation for `self` needed (duck typing)

### Files Affected

| File | Action |
|---|---|
| `src/colonyos/daemon.py` | Deleted (replaced by package) |
| `src/colonyos/daemon/__init__.py` | New — Daemon class + re-exports |
| `src/colonyos/daemon/_ui.py` | New — `DaemonError`, `_CombinedUI`, `_DaemonMonitorEventUI` |
| `src/colonyos/daemon/_watchdog.py` | New — `_WatchdogMixin` |
| `src/colonyos/daemon/_resilience.py` | New — `_ResilienceMixin` |
| `tests/test_daemon.py` | No changes |
| `src/colonyos/cli.py` | No changes |

## Persona Consensus

| Question | Consensus | Detail |
|---|---|---|
| Be more conservative? | **7/7 Yes** | 6 failures demand humility |
| Extract standalone classes? | **7/7 Yes** | Zero `self.*` coupling = zero risk |
| Don't split tests? | **7/7 Yes** | Tests are the regression oracle |
| Don't move methods off Daemon? | **6/7 Yes** | `patch.object` targets break |
| Use mixins? | **1/7 Yes** (Karpathy) | Only pattern that preserves `self` |
| No composition/thin wrappers? | **6/7 Yes** | Just indirection with no benefit |

**Tension resolved:** This plan follows the 7/7 consensus on conservatism AND uses Karpathy's mixin insight for the watchdog/recovery clusters only — the two most self-contained method groups with the fewest cross-references to other Daemon methods.

## Success Metrics

1. All 71 tests in `test_daemon.py` pass at every commit
2. Zero changes to `tests/test_daemon.py`
3. Zero changes to `src/colonyos/cli.py`
4. `daemon/__init__.py` reduced to ~2,100 lines (from 2,655)
5. 4 new files created under `src/colonyos/daemon/`
6. `mypy` and linting pass (if configured)

## Open Questions

1. **Should `_run_pipeline_for_item` join the resilience mixin?** It's at line 1584, adjacent to recovery methods, but has complex Daemon state coupling. Deferred for now.
2. **Should we extract `_handle_control_command` into a `_ControlMixin`?** It's relatively self-contained (~55 lines) but small enough to not warrant its own file.
3. **Future mixin candidates:** Notifications (~450 lines), Scheduling (~330 lines), Execution (~260 lines). Each should be a separate follow-up PR.
