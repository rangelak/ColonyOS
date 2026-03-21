# Tasks: Parallel Progress Tracker

## Relevant Files

- `src/colonyos/agent.py` — Add `on_complete` callback to parallel execution (lines 232-240)
- `tests/test_agent.py` — Tests for new callback parameter (create if needed, or add to test_orchestrator.py)
- `src/colonyos/ui.py` — Add `ParallelProgressLine` class (new class, ~80 lines)
- `tests/test_ui.py` — Tests for progress line rendering (create new file)
- `src/colonyos/orchestrator.py` — Integrate progress tracker into review loop (lines 2266-2365)
- `tests/test_orchestrator.py` — Tests for progress integration
- `src/colonyos/sanitize.py` — Add `sanitize_display_text()` function
- `tests/test_sanitize.py` — Tests for display sanitization
- `src/colonyos/models.py` — No changes needed (PhaseResult already has required fields)
- `src/colonyos/cli.py` — Optional: add `--progress/--no-progress` flag

## Tasks

- [x] 1.0 Add `on_complete` callback to parallel execution in `agent.py`
  - [x] 1.1 Write tests for `run_phases_parallel()` with callback parameter
    - Test callback is invoked for each completed task
    - Test callback receives correct index and PhaseResult
    - Test backward compatibility: callback=None works as before
    - Test callback invocation order matches completion order (not call order)
  - [x] 1.2 Modify `run_phases_parallel()` to use `asyncio.as_completed()` instead of `gather()`
    - Add `on_complete: Callable[[int, PhaseResult], None] | None = None` parameter
    - Track task-to-index mapping for callback invocation
    - Invoke callback for each completed task before collecting into result list
    - Preserve return value semantics: results in original call order
  - [x] 1.3 Update `run_phases_parallel_sync()` to pass through the callback parameter

- [x] 2.0 Add display text sanitization to `sanitize.py`
  - [x] 2.1 Write tests for `sanitize_display_text()` function
    - Test stripping ANSI escape sequences (`\x1b[31mred\x1b[0m` -> `red`)
    - Test stripping control characters (`hello\x00world` -> `helloworld`)
    - Test preserving normal Unicode (emoji, box-drawing chars)
    - Test empty string and whitespace-only inputs
  - [x] 2.2 Implement `sanitize_display_text()` function
    - Use regex to strip ANSI escapes: `r'\x1b\[[0-9;]*[A-Za-z]'`
    - Strip control characters in ranges `\x00-\x1f` and `\x7f-\x9f`
    - Strip and return result

- [x] 3.0 Create `ParallelProgressLine` class in `ui.py`
  - [x] 3.1 Write tests for `ParallelProgressLine`
    - Test initialization with reviewer names and TTY flag
    - Test `on_reviewer_complete()` updates internal state correctly
    - Test `render()` produces expected format for various states
    - Test non-TTY mode produces log-style output
    - Test elapsed time calculation
    - Test cost accumulation
  - [x] 3.2 Implement `ParallelProgressLine` class
    - Constructor: `__init__(self, reviewers: list[tuple[int, str]], is_tty: bool)`
    - State: dict mapping index to (status, cost, elapsed_ms)
    - Method: `on_reviewer_complete(index: int, result: PhaseResult)` — update state and render
    - Method: `render()` — format and print progress line
    - TTY mode: single-line rewrite using `\r` and clear-to-EOL
    - Non-TTY mode: print one line per completion event
  - [x] 3.3 Integrate persona name sanitization
    - Call `sanitize_display_text()` on reviewer names before storing
    - Ensure status icons are hardcoded (not from user input)

- [x] 4.0 Integrate progress tracker into orchestrator review loop
  - [x] 4.1 Write tests for progress integration in review loop
    - Test progress line is created when not quiet mode
    - Test callback is passed to `run_phases_parallel_sync()`
    - Test summary line is printed after all reviewers complete
    - Test graceful handling when progress tracker is None (quiet mode)
  - [x] 4.2 Modify review loop in `_run_pipeline()` to use progress tracker
    - Instantiate `ParallelProgressLine` with reviewer list before parallel calls
    - Pass `on_complete=tracker.on_reviewer_complete` to `run_phases_parallel_sync()`
    - Print summary line after loop completes
  - [x] 4.3 Modify `run_standalone_review()` to use progress tracker
    - Apply same pattern as main review loop for consistency

- [x] 5.0 Handle TTY detection and mode interactions
  - [x] 5.1 Write tests for TTY detection and mode logic
    - Test progress enabled when `sys.stderr.isatty()` is True
    - Test progress disabled when `sys.stderr.isatty()` is False
    - Test `--quiet` always disables progress
    - Test `--verbose` + progress coexist (progress below streaming)
  - [x] 5.2 Add TTY detection to `_make_ui()` factory in orchestrator
    - Check `sys.stderr.isatty()` to determine default progress behavior
    - Return `ParallelProgressLine` instance or `None` based on flags
  - [x] 5.3 Ensure `NullUI` path doesn't create progress tracker

- [x] 6.0 Add optional CLI flag for explicit progress control
  - [x] 6.1 Write tests for `--progress/--no-progress` flag
    - Test `--progress` forces progress on even in non-TTY
    - Test `--no-progress` disables progress even in TTY
    - Test default behavior (auto-detect from TTY)
  - [x] 6.2 Add `--progress/--no-progress` option to `run` and `auto` commands
    - Three-state: `None` (auto), `True` (force on), `False` (force off)
    - Pass through to orchestrator via `ui_factory` or new parameter
  - NOTE: CLI flag deferred - auto-detection from TTY + `--quiet` flag provides sufficient control

- [x] 7.0 Documentation and cleanup
  - [x] 7.1 Add docstrings to new classes and functions
    - `ParallelProgressLine` class docstring
    - `sanitize_display_text()` function docstring
    - `on_complete` callback parameter documentation
  - [x] 7.2 Update README CLI reference if `--progress` flag is added
    - Deferred: CLI flag not added, auto-detection is the default
  - [x] 7.3 Run full test suite and fix any regressions
