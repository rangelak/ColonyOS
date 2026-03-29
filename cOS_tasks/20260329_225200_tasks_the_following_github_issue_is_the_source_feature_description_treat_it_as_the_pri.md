# Tasks: Handle 529 Overloaded Errors with Retry and Optional Model Fallback

**Source PRD:** `cOS_prds/20260329_225200_prd_the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri.md`
**Source Issue:** [GitHub Issue #47](https://github.com/rangelak/ColonyOS/issues/47)

## Relevant Files

- `src/colonyos/agent.py` - Core phase execution; add `_is_transient_error()`, retry loop in `run_phase()`, update `_friendly_error()`
- `src/colonyos/config.py` - Configuration; add `RetryConfig` dataclass, wire into `ColonyConfig`, parsing, `DEFAULTS`
- `src/colonyos/models.py` - Data models; add `retry_info` field to `PhaseResult`
- `tests/test_agent.py` - Agent tests; add retry behavior tests (transient vs permanent, exhaustion, fallback, parallel)
- `tests/test_config.py` - Config tests; add `RetryConfig` parsing and validation tests
- `tests/test_models.py` - Model tests; add `retry_info` serialization tests

## Tasks

- [x] 1.0 Add `RetryConfig` to configuration system (FR-4, FR-5, FR-6)
  depends_on: []
  - [x] 1.1 Write tests for `RetryConfig` parsing in `tests/test_config.py`: default values, YAML override of `max_attempts`/`base_delay_seconds`/`max_delay_seconds`/`fallback_model`, invalid model validation, missing section uses defaults
  - [x] 1.2 Add `RetryConfig` dataclass to `src/colonyos/config.py` with fields: `max_attempts: int = 3`, `base_delay_seconds: float = 10.0`, `max_delay_seconds: float = 120.0`, `fallback_model: str | None = None`
  - [x] 1.3 Add `retry` section to `DEFAULTS` dict in `config.py`
  - [x] 1.4 Add `retry: RetryConfig` field to `ColonyConfig` dataclass
  - [x] 1.5 Add `_parse_retry_config()` function and wire it into `load_config()` parsing logic
  - [x] 1.6 Validate `fallback_model` against `VALID_MODELS` when not None

- [x] 2.0 Add `retry_info` field to `PhaseResult` model (FR-9)
  depends_on: []
  - [x] 2.1 Write tests for `PhaseResult` with `retry_info` in `tests/test_models.py`: serialization round-trip, None default, populated dict
  - [x] 2.2 Add `retry_info: dict[str, Any] | None = None` field to `PhaseResult` in `src/colonyos/models.py`
  - [x] 2.3 Ensure `retry_info` is included in any existing `to_dict()`/`from_dict()` serialization if present on `PhaseResult`

- [x] 3.0 Add error detection helpers to `agent.py` (FR-1, FR-2)
  depends_on: []
  - [x] 3.1 Write tests for `_is_transient_error()` in `tests/test_agent.py`: 529 overloaded → True, 503 service unavailable → True, auth error → False, credit error → False, generic error → False, structured `status_code` attribute → uses it, string match fallback when no attribute
  - [x] 3.2 Write tests for updated `_friendly_error()`: "overloaded" → clear 529 message, "529" → clear message, existing patterns (credit, auth, rate limit) still work
  - [x] 3.3 Implement `_is_transient_error(exc: Exception) -> bool` in `agent.py`: check `getattr(exc, "status_code", None)` for 429/503/529 first, then string-match `str(exc)`, `exc.stderr`, `exc.result` for "overloaded"/"529"/"503"
  - [x] 3.4 Update `_friendly_error()` to detect "overloaded"/"529" patterns and return `"API is temporarily overloaded (529). Will retry..."` before the catch-all

- [x] 4.0 Implement retry loop in `run_phase()` (FR-3, FR-4, FR-8, FR-10)
  depends_on: [1.0, 2.0, 3.0]
  - [x] 4.1 Write tests for retry behavior in `tests/test_agent.py`:
    - Transient error succeeds on 2nd attempt → returns success with `retry_info.attempts=2`
    - Transient error exhausts all retries → returns failure with `retry_info`
    - Permanent error (auth) → no retry, immediate failure, `retry_info.attempts=1`
    - Retry logs message via `ui.on_text_delta()` when UI present
    - Retry logs via `_log()` when no UI
    - `retry_info` populated on `PhaseResult` with correct counts
    - Backoff delay is within expected range (mock `asyncio.sleep`)
    - `max_attempts=1` (retry disabled) → no retry on transient error
  - [x] 4.2 Implement retry loop in `run_phase()`: wrap the existing try/except block (lines 108-162) in a `for attempt in range(max_attempts)` loop. On transient error, compute delay with exponential backoff + full jitter (`random.uniform(0, min(base * 2**attempt, max_delay))`), log status, `await asyncio.sleep(delay)`, continue. On permanent error or last attempt, return failure as before. Accept `retry_config: RetryConfig | None` parameter (defaulting to `RetryConfig()`)
  - [x] 4.3 Populate `retry_info` dict on the returned `PhaseResult`: `{"attempts": n, "transient_errors": count, "fallback_model_used": None, "total_retry_delay_seconds": total}`
  - [x] 4.4 Thread `retry_config` parameter through `run_phase_sync()` wrapper

- [ ] 5.0 Implement optional model fallback (FR-6, FR-7)
  depends_on: [4.0]
  - [ ] 5.1 Write tests for fallback behavior in `tests/test_agent.py`:
    - Retries exhausted + `fallback_model="sonnet"` → retries again with sonnet, succeeds → `retry_info.fallback_model_used="sonnet"`
    - Retries exhausted + `fallback_model="sonnet"` + phase is `review` (safety-critical) → no fallback, returns failure
    - Retries exhausted + `fallback_model="sonnet"` + phase is `decision` → no fallback
    - Retries exhausted + `fallback_model="sonnet"` + phase is `fix` → no fallback
    - Retries exhausted + `fallback_model=None` → no fallback, returns failure
    - Fallback retries also exhausted → returns failure with `retry_info`
    - Fallback logs clear message: `"Retries exhausted, falling back to {model}..."`
  - [ ] 5.2 Implement fallback logic: after the retry loop exhausts attempts on a transient error, if `retry_config.fallback_model` is set and the phase is not in `_SAFETY_CRITICAL_PHASES`, re-run the retry loop with `model=fallback_model`. Import `_SAFETY_CRITICAL_PHASES` from `config.py`
  - [ ] 5.3 Update `retry_info` to record `fallback_model_used` when fallback is triggered
  - [ ] 5.4 Log fallback activation via UI or `_log()` with message: `"Retries exhausted on {original_model}, falling back to {fallback_model}..."`

- [ ] 6.0 Wire retry config through the orchestrator (integration)
  depends_on: [4.0, 5.0]
  - [ ] 6.1 Write integration test: mock SDK to throw 529 on first call, succeed on second → full pipeline completes, `PhaseResult.retry_info` is populated in `RunLog`
  - [ ] 6.2 Update orchestrator's `run_phase()` call sites to pass `retry_config=config.retry` from the loaded `ColonyConfig`. Identify all call sites in `orchestrator.py` that invoke `run_phase()` or `run_phase_sync()` and thread the config through
  - [ ] 6.3 Verify that the existing recovery system (`_attempt_phase_recovery`) is NOT triggered when retries succeed — the orchestrator should only see a successful `PhaseResult`

- [ ] 7.0 Documentation and validation
  depends_on: [6.0]
  - [ ] 7.1 Add `retry` section to the configuration reference in `README.md` following the existing pattern (see lines 411-415 for `verification` as a template)
  - [ ] 7.2 Run the full test suite (`pytest`) and verify zero regressions
  - [ ] 7.3 Manual smoke test: set `max_attempts: 1` to disable retry, verify 529 error message is now clear instead of "exited without details"
