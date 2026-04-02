# PRD: Pre-Delivery Test Verification Phase

## Introduction/Overview

ColonyOS currently runs a pipeline of `Plan → Implement → Review/Fix → Decision Gate → Learn → Deliver → CI Fix`. The **Deliver** phase creates a PR without first verifying that the project's test suite passes. This means broken PRs regularly land in the open PR queue against `main`, wasting CI minutes and creating noisy red checks that require manual intervention.

This feature adds a **Verify phase** to the main pipeline — inserted between Learn and Deliver — that runs the project's full test suite, attempts auto-fixes if tests fail, and hard-blocks delivery if failures persist. The goal is simple: **never open a PR you know is broken**.

The infrastructure for this already exists in embryonic form: `Phase.VERIFY` is defined in `src/colonyos/models.py` (line 74), and the thread-fix sub-flow already implements a read-only verify step at `orchestrator.py` lines 3979–4012 using `instructions/thread_fix_verify.md`. This feature promotes that pattern to the main pipeline with the addition of a verify-fix loop.

## Goals

1. **Zero known-broken PRs**: No PR should be opened to `main` with test failures that were detectable locally.
2. **Autonomous fix**: When tests fail, the pipeline should attempt auto-repair (up to 2 attempts) before blocking delivery.
3. **Minimal budget impact**: Verify should be cheap — test execution is read-only; only fix iterations cost real tokens.
4. **Seamless integration**: The verify phase should follow the same patterns as existing phases (budget guards, heartbeat, UI, recovery, resume).

## User Stories

1. **As a developer using ColonyOS**, I want the pipeline to run the full test suite before opening a PR, so I don't get notified about CI failures on PRs that could have been caught locally.
2. **As a developer**, I want the pipeline to auto-fix simple test failures (import errors, assertion mismatches) without human intervention, so the pipeline can self-heal.
3. **As a developer**, I want the pipeline to hard-stop if it can't fix tests after 2 attempts, so broken code never reaches `main`.
4. **As a developer**, I want to see clear failure logs when verify blocks delivery, so I know exactly what to fix manually.
5. **As a power user**, I want to disable verify via config (`phases.verify: false`) if my project has a 45-minute test suite.

## Functional Requirements

1. **FR-1: Verify phase in main pipeline** — Insert a Verify phase between Learn and Deliver in `_run_pipeline()` (orchestrator.py line ~4901). The verify agent runs the project's test suite using read-only tools (`["Read", "Bash", "Glob", "Grep"]`), reports pass/fail.

2. **FR-2: Verify-fix loop** — If verify detects test failures, run a fix agent (with write tools) to repair the code, then re-verify. Loop up to `max_verify_fix_attempts` (default: 2) times, matching the pattern of the review-fix loop (orchestrator.py line 4718).

3. **FR-3: Hard-block delivery on persistent failure** — If the verify-fix loop exhausts all attempts, mark the run as `FAILED` via `_fail_run_log()` and do **not** proceed to Deliver. Log the failing test output clearly.

4. **FR-4: Budget guard** — Before each verify/fix iteration, check that `remaining >= per_phase`. If budget is exhausted, stop the loop and block delivery (same pattern as review loop, line 4720–4729).

5. **FR-5: Config integration** — Add `verify: bool = True` to `PhasesConfig` (config.py line 147) and `"verify": True` to `DEFAULTS["phases"]` (config.py line 38). Add a `VerifyConfig` dataclass with `max_fix_attempts: int = 2`.

6. **FR-6: Instruction templates** — Create `instructions/verify.md` (read-only test runner, based on `thread_fix_verify.md`) and `instructions/verify_fix.md` (write-enabled fix agent that receives test failure output).

7. **FR-7: Resume support** — Update `_compute_next_phase()` (orchestrator.py line 3011) and `_SKIP_MAP` (line 3030) to include the verify phase in the resume chain: `decision → verify`, `verify → deliver`.

8. **FR-8: Heartbeat + UI** — Touch heartbeat before verify (for watchdog compatibility). Display phase header via `_make_ui()` or `_log()`, consistent with other phases.

9. **FR-9: Verify in thread-fix flow** — The existing thread-fix verify (line 3979) continues to work as-is. No changes needed to the thread-fix sub-flow.

## Non-Goals

- **Not replacing CI Fix**: The post-delivery CI Fix phase handles environment-specific failures (GitHub Actions runners, secrets, Docker). Verify catches local test failures only. They complement each other.
- **Not hardcoding test commands**: The verify agent discovers the appropriate test commands from project files (`pyproject.toml`, `package.json`, `Makefile`), not from config. An optional `verify.test_commands` override may be added in a future iteration.
- **Not running linters/type-checkers**: Scope is limited to the test suite. Linting is handled by pre-commit hooks.
- **Not modifying the thread-fix verify flow**: That flow already works; this feature only adds verify to the main pipeline.

## Technical Considerations

### Insertion Point
The verify phase goes between Learn and Deliver in `_run_pipeline()` at orchestrator.py line ~4901. This is after the decision gate has approved the code (GO verdict) and before any PR is created.

### Two-Agent Pattern
Like the review-fix loop, verify uses two distinct agent invocations per iteration:
1. **Verify agent** (read-only): Runs tests, reports failures. Tools: `["Read", "Bash", "Glob", "Grep"]`. Uses `instructions/verify.md`.
2. **Fix agent** (write-enabled): Receives test failure output, fixes code. Full tool access. Uses `instructions/verify_fix.md`.

This separation preserves audit boundaries — you can always see what was observed vs. what was changed.

### Model Selection
The verify agent (read-only test execution) should default to a cheaper model (haiku) since it doesn't require frontier reasoning. The fix agent should use the configured default model (opus) since diagnosing and fixing test failures requires strong reasoning.

### Budget Impact
Adding 1–3 new phase invocations (1 verify + 0–2 fix iterations) increases run cost. The `per_run` default of $15.0 may need a bump to $20.0 to accommodate. Each verify/fix iteration is individually gated by `per_phase`.

### Existing Patterns to Follow
- Budget guard: review loop lines 4720–4729
- Heartbeat touch: all phases call `_touch_heartbeat(repo_root)`
- UI header: `_make_ui()` + `phase_header()` / `_log()` fallback
- Phase append: `_append_phase(result)` + `log.phases.append()`
- Thread-fix verify: lines 3979–4012 (reference implementation)

### Safety-Critical Phase
The verify-fix agent should be added to `_SAFETY_CRITICAL_PHASES` (config.py line 25) to prevent model fallback during fix iterations, consistent with the review/fix phases.

## Persona Consensus Summary

| Question | Resolution | Agreement |
|----------|-----------|-----------|
| Scope of "CLI tests" | Full test suite (auto-detected by agent) | **7/7 unanimous** |
| Auto-fix or block? | Auto-fix with bounded retry, then hard-block | **7/7 unanimous** |
| Test command discovery | Agent discovers from project files, not hardcoded | **6/7** (PSE suggests optional config override) |
| Exhausted retries → ? | Block delivery, never open broken PR | **7/7 unanimous** |
| Budget allocation | Use existing `per_phase`, no special knob | **6/7** (Security suggests lower default) |
| Verify vs CI Fix | Complement, not replace | **7/7 unanimous** |
| Default on/off | On by default (`phases.verify: true`) | **7/7 unanimous** |
| Instruction template | Separate from thread-fix (new `verify.md` + `verify_fix.md`) | **5/7** (Seibel/Jobs say reuse; others say fork) |

### Points of Tension
- **Template reuse vs. fork**: Seibel and Jobs favor reusing `thread_fix_verify.md` for simplicity. PSE, Security, Karpathy, and Torvalds want separate templates for richer context and independent evolution. **Resolution**: Create new `verify.md` based on the same content but with pipeline context (branch name, change summary). The thread-fix template stays as-is.
- **Optional test_commands config**: PSE and Karpathy suggest allowing explicit test commands in config for non-standard projects. **Resolution**: Defer to v2 — agent auto-detection is sufficient for v1.

## Success Metrics

1. **0% of PRs opened by ColonyOS have known test failures** (measured by CI pass rate on first push).
2. **Verify-fix loop resolves ≥80% of test failures** without human intervention.
3. **Budget overhead ≤$2 per run** for the verify phase on average.
4. **No regressions** in existing pipeline behavior (review-fix loop, thread-fix, CI fix).

## Open Questions

1. Should the `per_run` budget default increase from $15.0 to $20.0 to accommodate the new phases? Or is $15.0 sufficient since verify is cheap?
2. Should verify use haiku by default or inherit the global model setting? (Persona consensus leans toward haiku for cost savings.)
3. In a future iteration, should verify support an explicit `test_commands` config for monorepos/non-standard projects?
