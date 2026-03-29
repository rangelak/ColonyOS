# PRD: Handle 529 Overloaded Errors with Retry and Optional Model Fallback

## Source Issue

[GitHub Issue #47: Handle 529 Overloaded errors with retry and optional model fallback](https://github.com/rangelak/ColonyOS/issues/47)

## Introduction/Overview

When the Anthropic API returns HTTP 529 (overloaded), ColonyOS phases fail immediately with a misleading error message ("the Claude CLI exited without details") and no retry. This wastes all prior phase spend and breaks user trust in autonomous workflows.

This feature adds a lightweight retry layer with exponential backoff inside `run_phase()` in `agent.py` — below the orchestrator's heavyweight recovery system — so that transient 529 errors are handled transparently without triggering diagnostic agents or nuke recovery. Optionally, users can configure a fallback model that activates only after retries are exhausted, with hard guards preventing fallback on safety-critical phases.

## Goals

1. **Detect 529/overloaded errors** — Add pattern matching in `_friendly_error()` so 529 errors produce a clear, actionable message instead of the generic "exited without details" fallthrough.
2. **Retry with backoff** — Automatically retry phases that fail with transient 529 errors using exponential backoff with jitter, defaulting to 3 attempts.
3. **Optional model fallback** — Allow users to configure a fallback model (e.g., `sonnet`) that activates only after retries are exhausted, with hard blocks on safety-critical phases (`review`, `decision`, `fix`).
4. **Observability** — Record retry attempts and fallback events in `PhaseResult` so they flow into `RunLog` for post-run analysis.
5. **User communication** — Surface retry status through existing UI and logging channels so users know the system is recovering, not stuck.

## User Stories

1. **As a user running `colonyos run`**, when the API is temporarily overloaded, I want the system to automatically retry so my $10+ multi-phase run doesn't die from a transient hiccup.
2. **As a daemon operator**, I want 529 errors to resolve automatically so overnight autonomous runs don't halt and require manual restart.
3. **As a cost-conscious user**, I want the option to fall back to a lighter model rather than fail completely, but only for phases where quality tradeoffs are acceptable.
4. **As a user debugging a failed run**, I want to see in `colonyos show` how many retries occurred and whether a fallback model was used.

## Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | `_friendly_error()` in `agent.py` detects "overloaded", "529", and "503" patterns and returns a clear message: `"API is temporarily overloaded (529). Will retry..."` |
| FR-2 | A new `_is_transient_error()` helper in `agent.py` classifies exceptions as transient (529 overloaded, 503 service unavailable) vs permanent (auth, credit, logic failure) by checking structured attributes first, then falling back to string matching |
| FR-3 | `run_phase()` wraps the `query()` call in a retry loop: on transient error, wait with exponential backoff + full jitter, then restart the phase from scratch (not resume) |
| FR-4 | Default retry config: `max_attempts=3`, `base_delay_seconds=10.0`, `max_delay_seconds=120.0`. Jitter is implicit (full jitter: `uniform(0, computed_delay)`), not configurable |
| FR-5 | A new `RetryConfig` dataclass in `config.py` holds retry settings, nested under `ColonyConfig` as `retry: RetryConfig`. Config section in YAML: `retry:` |
| FR-6 | `RetryConfig` includes an optional `fallback_model: str | None` (default `None` = disabled). When set and retries are exhausted on a transient error, re-attempt the phase with the fallback model |
| FR-7 | Fallback is **hard-blocked** for safety-critical phases (`_SAFETY_CRITICAL_PHASES`: `review`, `decision`, `fix`). If retries exhaust on these phases, the phase fails — no fallback regardless of config |
| FR-8 | Each retry attempt logs a message via `ui.on_text_delta()` (if UI present) or `_log()`: `"API overloaded, retrying in {delay:.0f}s (attempt {n}/{max})..."` |
| FR-9 | `PhaseResult` gains an optional `retry_info: dict | None` field recording: `attempts` (int), `transient_errors` (int), `fallback_model_used` (str or None), `total_retry_delay_seconds` (float) |
| FR-10 | When running parallel phases via `run_phases_parallel()`, each phase retries independently within its own `run_phase()` call. No cross-phase retry coordination |

## Non-Goals

- **Unifying all retry mechanisms** — The existing `RecoveryConfig` (orchestrator-level logic failure recovery), `CIFixConfig` (CI pipeline retry), and review/fix loops serve fundamentally different purposes. This feature adds transport-level retry only. Unification is out of scope.
- **Prompt adaptation for fallback model** — System prompts are not modified based on the model. The same prompt is used regardless of whether the primary or fallback model is active.
- **Resume-based retry** — When a 529 hits, the `query()` generator throws and no `ResultMessage` (and thus no `session_id`) is received. Retry restarts the phase from scratch. Resume-based retry is architecturally infeasible for 529s.
- **Budget deduction for failed attempts** — Partial cost from a 529'd attempt is not tracked by the SDK (no `ResultMessage` returned). Retry gets the full phase budget. The per-run budget cap in the orchestrator provides the safety net.
- **Cross-phase thundering herd mitigation** — Full jitter on each independent retry provides sufficient decorrelation for the typical 3-4 concurrent agents. No cross-phase coordination mechanism.

## Technical Considerations

### Architecture: Lightweight Layer Below Recovery

The retry loop lives inside `run_phase()` in `src/colonyos/agent.py`, wrapping the `async for message in query(...)` block (line 109). This ensures:

- The **orchestrator** (`orchestrator.py`) never sees transient 529 errors — they're resolved transparently at the agent layer
- The **heavyweight recovery system** (`_attempt_phase_recovery()`, `_run_nuke_recovery()`) is only triggered for genuine logic failures, not API hiccups
- **Parallel execution** (`run_phases_parallel()`) works unchanged — each `run_phase()` call handles its own retries independently

### Error Detection Strategy

The `_is_transient_error()` helper checks:
1. **Structured attributes first** — `getattr(exc, "status_code", None)` for 429, 503, 529
2. **String matching fallback** — Check `str(exc)`, `exc.stderr`, `exc.result` for "overloaded", "529", "503"
3. A code comment notes this is a workaround until the SDK provides structured error types

### Key Files

| File | Changes |
|------|---------|
| `src/colonyos/agent.py` | Add `_is_transient_error()`, retry loop in `run_phase()`, update `_friendly_error()` |
| `src/colonyos/config.py` | Add `RetryConfig` dataclass, wire into `ColonyConfig`, add parsing logic, add to `DEFAULTS` |
| `src/colonyos/models.py` | Add `retry_info` field to `PhaseResult` |
| `tests/test_agent.py` | Add retry tests: success after N failures, permanent error no retry, retries exhausted, fallback, safety-critical fallback blocked, parallel retry independence |
| `tests/test_config.py` | Add `RetryConfig` parsing tests |
| `tests/test_models.py` | Add `retry_info` serialization tests |

### Relationship to Existing Config Patterns

The `RetryConfig` follows the established pattern of `CIFixConfig`, `RecoveryConfig`, etc.:
- Dataclass with sensible defaults
- Parsed from YAML via `_parse_*` function
- Nested under `ColonyConfig`
- Added to `DEFAULTS` dict

### Parallel Phase Behavior

In `run_phases_parallel()` (agent.py line 239), tasks are created via `asyncio.create_task(run_phase(**call_kwargs))`. Since retry lives inside `run_phase()`, each parallel phase retries independently. If one reviewer hits 529 while others complete, the retrying reviewer continues without blocking the pipeline — `asyncio.wait(FIRST_COMPLETED)` delivers completed results immediately.

## Persona Synthesis

### Strong Consensus (All 7 Personas Agree)

- **Ship retry-only first, add fallback later** — Every persona recommended Approach A (retry with backoff) as the initial ship. Fallback introduces quality tradeoffs that need separate validation. *However*, the issue spec requests both, so we include fallback as opt-in (disabled by default).
- **Retry belongs in `agent.py`, not the orchestrator** — Unanimous agreement that 529 is a transport-level concern, not a logic failure. It should be invisible to the orchestrator's recovery system.
- **Safety-critical phases must never fall back** — `_SAFETY_CRITICAL_PHASES` (`review`, `decision`, `fix`) should hard-block model fallback regardless of config.
- **User must be informed of retries** — Brief, calm status messages. Never silent, never alarming.

### Key Tension: Resume vs Restart

- **Karpathy** strongly favors resume to preserve LLM conversation context, arguing that mid-implement context loss is "catastrophic"
- **All other personas** favor restart, noting that 529 means no `ResultMessage` was received and thus no `session_id` is available
- **Resolution**: Restart from scratch. The SDK's `query()` generator doesn't yield a `session_id` before throwing on 529, making resume technically infeasible. This is noted in Non-Goals.

### Key Tension: Config Approach

- **Linus Torvalds** argues for hard-coded defaults with zero config: "Every config knob is a maintenance burden"
- **Michael Seibel** suggests adding fields to existing `RecoveryConfig` rather than a new dataclass
- **Systems Engineer** recommends a dedicated `RetryConfig` following the established pattern
- **Resolution**: New `RetryConfig` dataclass following the established codebase pattern (`CIFixConfig`, `RecoveryConfig`). The defaults are good enough that most users never touch it, but power users (daemon operators) may need to tune `max_attempts` or enable `fallback_model`.

### Security Considerations (Staff Security Engineer)

- **Budget amplification**: Partial costs from 529'd attempts are untracked. Accepted risk — per-run budget cap provides outer safety net.
- **Fallback model security**: Weaker models may be more susceptible to prompt injection. Mitigated by hard-blocking fallback on safety-critical phases.
- **Error message disclosure**: 529 response bodies could leak API internals. The retry handler surfaces a generic message, not the raw response.

## Success Metrics

1. **Retry recovery rate** — % of 529 errors that succeed on retry (target: >90%)
2. **Run completion rate** — Overall pipeline completion rate should increase after this change
3. **Mean retries per run** — Track via `retry_info` in `PhaseResult` to inform default tuning
4. **Zero false retries** — Permanent errors (auth, credit) must never trigger retry

## Open Questions

1. **SDK structured errors** — Does `claude_agent_sdk` expose a `status_code` attribute on exceptions? If so, use it instead of string matching. If not, file an SDK issue.
2. **Implement phase idempotency** — If a 529 hits mid-implement after tool calls have mutated the working tree, restarting could conflict with partial changes. Should we `git stash` before retrying implement phases specifically? (The systems engineer persona raised this; worth investigating but may be over-engineering for v1.)
3. **Fallback for `implement` phase** — The issue proposes fallback for all phases, but implement is arguably the highest-quality-sensitivity phase. Should `implement` join `_SAFETY_CRITICAL_PHASES` for fallback purposes? Defer to user feedback.
