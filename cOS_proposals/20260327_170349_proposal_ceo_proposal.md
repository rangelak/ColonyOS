## Proposal: Resilient API Retry with Model Fallback

### Rationale
ColonyOS runs autonomous 24+ hour loops (`colonyos auto --loop`) where a single transient 529 Overloaded error currently triggers the heavyweight recovery system (auto-recovery agent → nuke escalation) — designed for *logic* failures, not *infrastructure* hiccups. This wastes compute, can destroy good in-progress work, and is the #1 reliability gap for unattended autonomous operation. Adding exponential-backoff retry with optional model fallback makes the entire pipeline dramatically more robust with minimal code change.

### Builds Upon
- "Per-Phase Model Override Configuration" (provides the `phase_models` and `get_model()` infrastructure to enable fallback model selection)
- "Autonomous CEO Stage" (the primary consumer of long-running unattended loops most affected by transient failures)
- "Rich Streaming Terminal UI" (retry status should surface in the streaming UI)

### Inspired By
RuFlo's adaptive routing concept — not full Q-Learning, but the simpler idea that when one model path fails transiently, the system should automatically try an alternative rather than escalating to destructive recovery.

### Feature Request
**Issue: #47**

Add a retry-with-backoff layer inside `agent.py`'s `run_phase()` that catches transient API errors (HTTP 529 Overloaded, rate limits, timeout errors) and retries with exponential backoff before surfacing the failure to the orchestrator's recovery system. Include optional model fallback so that if a phase configured for `opus` hits persistent overload, it can fall back to `sonnet` and still complete.

**Specific requirements:**

1. **Retry logic in `agent.py`**: Wrap the `query()` call in a retry loop that detects transient errors (529 overloaded, rate limit, connection timeout) via error message classification in `_friendly_error()` or a new `_is_transient()` helper. Use exponential backoff with jitter (starting at 5s, max 120s).

2. **Configuration in `config.py`**: Add a `ResilienceConfig` dataclass with:
   - `max_retries: int = 3` — max retry attempts for transient errors before failing
   - `initial_backoff_seconds: float = 5.0` — starting backoff delay
   - `max_backoff_seconds: float = 120.0` — backoff cap
   - `fallback_model: Optional[str] = None` — model to try if primary model is persistently overloaded (e.g., `"sonnet"` as fallback for `"opus"`)
   - `fallback_after_retries: int = 2` — switch to fallback model after N failed retries of primary

3. **Model fallback**: After `fallback_after_retries` failures on the primary model, reconstruct `ClaudeAgentOptions` with the fallback model and retry. Log a warning when falling back. Record which model actually completed the phase in `PhaseResult.model`.

4. **UI integration**: When retrying, emit a log line / UI callback so the TUI status bar shows "Retrying (attempt 2/3, backoff 10s...)" or "Falling back to sonnet..." rather than appearing frozen.

5. **Distinguish transient vs permanent errors**: Auth failures, credit balance errors, and logic errors should NOT be retried — only 529, rate limit, and connection/timeout errors. Add an `_is_transient(exc)` classifier function.

6. **Tests**: Unit tests for retry logic (mock `query()` to fail N times then succeed), backoff calculation, model fallback trigger, transient error classification, and config parsing. Integration test showing that a non-transient error (auth) is NOT retried.

**Acceptance criteria:**
- A phase hitting a 529 error retries up to `max_retries` times with exponential backoff before failing
- If `fallback_model` is configured, switches to it after `fallback_after_retries` failures
- Non-transient errors (auth, credits) fail immediately without retry
- Retry/fallback activity is visible in TUI and logged
- All existing tests continue to pass
- New config section is optional with sensible defaults (works without any config changes)
