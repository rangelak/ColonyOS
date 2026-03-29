# Review by Linus Torvalds (Round 2)

All right. I've read the PRD, the full diff across all files, the test suite (2287 passed, zero failures), and the implementation in detail. Now let me write the review.

---

## Linus Torvalds Review

I've read every changed line. Let me be direct.

### The Good

The architecture is **correct**. Retry lives inside `run_phase()`, below the orchestrator's recovery system. This is exactly where it belongs — transient transport errors have no business triggering nuke recovery or diagnostic agents. The person who designed this understood the layering.

The extraction of `_run_phase_attempt()` was the right call. The original `run_phase()` was already pushing it; adding a retry loop inside it would have made it unreadable. Now you have a clean separation: streaming/query logic in one function, retry/fallback orchestration in the other.

`_is_transient_error()` checks structured attributes first, string-matches second. That's the right priority. The word-boundary regexes for `\b529\b` and `\b503\b` fix the false-positive problem that was flagged. Good.

`RetryConfig` follows the established pattern (`CIFixConfig`, `RecoveryConfig`). The validation in `_parse_retry_config` is thorough — bounds checking, model allowlist, warning on high values without a hard cap. Sensible.

`RetryInfo` is a frozen dataclass. Good. The previous `dict[str, Any]` was sloppy — this is typed, immutable, and serializable. The serialization/deserialization in `_save_run_log`/`_load_run_log` is correct.

2287 tests pass. 231 new tests across three files. Test coverage hits the important cases: transient vs permanent detection, retry exhaustion, fallback, safety-critical blocking, false-positive string patterns.

### The Findings

**1. [src/colonyos/agent.py:248]: `resume` kwarg leaks into retry attempts.**
After a 529, there's no session to resume — the query threw before yielding a `ResultMessage`. But the retry loop passes the same `resume` session ID on every attempt. If `resume="sess-abc"` was passed into `run_phase()`, the second attempt will try to resume that same session, which is wrong — it should restart from scratch. The `resume` kwarg needs to be set to `None` after the first attempt fails with a transient error. This is a **real bug** in the retry-after-resume path.

**2. [src/colonyos/agent.py:264-266]: `_is_transient_error()` called twice on the same exception.**
Line 264 checks `not _is_transient_error(exc)`, then line 266 checks `_is_transient_error(exc)` again, then line 268 checks it a *third time*. This is a function with regex matching — it's not free. Extract to a local boolean: `is_transient = _is_transient_error(exc)`. This is basic.

**3. [src/colonyos/agent.py:94-95]: `_friendly_error()` uses bare substring matching while `_is_transient_error()` uses word-boundary regexes.**
You fixed the detection function to use `\b529\b` to avoid false positives, but `_friendly_error()` still does `if "529" in lower`. So `_friendly_error` will return the "API is temporarily overloaded" message for an error like "Error at line 529 of config.py". Inconsistent. Either use the same patterns or call `_is_transient_error` from `_friendly_error`.

**4. [src/colonyos/agent.py:326-332]: The `for/else/continue` dance at the bottom of the retry loop is needlessly clever.**
```python
        else:
            continue
        continue
```
Two `continue` statements, one in an `else` clause, one bare — this is the kind of Python that makes people hate Python. The `else` on a `for` loop is a well-known readability trap. This exists only to handle the defensive case of `pass_max == 0`, which is impossible given `max_attempts >= 1` validation. Delete the `else` clause and the trailing `continue`. If the inner loop breaks, the outer loop continues naturally.

**5. [src/colonyos/config.py:22]: `_SAFETY_CRITICAL_PHASES` uses raw strings instead of `Phase` enum values.**
```python
_SAFETY_CRITICAL_PHASES: frozenset[str] = frozenset({"review", "decision", "fix"})
```
And it's compared via `phase.value not in _SAFETY_CRITICAL_PHASES`. If someone renames a `Phase` enum value, this silently stops blocking fallback on that phase. Use `frozenset({Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value})` — at least you get an `AttributeError` if the enum member is removed. Or better, make it `frozenset[Phase]` and compare with `phase not in _SAFETY_CRITICAL_PHASES`.

**6. [src/colonyos/orchestrator.py]: `retry_config=config.retry` is passed to every single `run_phase_sync()` call — 20+ call sites.**
This is correct but tedious. If you ever add another global config that `run_phase` needs, you'll be editing 20+ call sites again. Consider whether `run_phase` should just take the full `ColonyConfig` (or a subset interface) instead of threading individual fields. Not a blocker for this PR, but the pattern is heading toward unmaintainable.

### Checklist

**Completeness**
- [x] FR-1 through FR-10 are all implemented
- [x] All tasks complete
- [x] No placeholder/TODO code (one design-note comment is appropriate)

**Quality**
- [x] 2287 tests pass, zero regressions
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies (only stdlib `random`, `re`)
- [x] No unrelated changes (`.colonyos/daemon_state.json` was cleaned up in fix commit)

**Safety**
- [x] No secrets or credentials
- [x] No destructive operations
- [x] Error handling present for all failure cases
- [ ] **`resume` kwarg bug** — retry after 529 with an active session will attempt to resume a dead session

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/agent.py:248]: `resume` kwarg leaks into retry attempts — after a 529 kills a query, subsequent retries should NOT try to resume the dead session. Set `resume = None` after the first transient failure.
- [src/colonyos/agent.py:264-268]: `_is_transient_error(exc)` called 3 times on the same exception with regex matching. Extract to a local boolean.
- [src/colonyos/agent.py:94-95]: `_friendly_error()` uses bare `"529" in lower` substring match while `_is_transient_error()` uses word-boundary regex `\b529\b`. Inconsistent false-positive behavior between the two functions.
- [src/colonyos/agent.py:326-332]: `for/else/continue/continue` pattern is needlessly clever. The `else` clause handles an impossible case (`pass_max == 0`). Remove it.
- [src/colonyos/config.py:22]: `_SAFETY_CRITICAL_PHASES` uses raw strings instead of `Phase` enum values — silent failure if enum members are renamed.
- [src/colonyos/orchestrator.py]: `retry_config=config.retry` threaded through 20+ call sites. Not a blocker but worth noting the config-threading pattern is getting unwieldy.

SYNTHESIS:
The architecture is sound — retry below recovery, transient detection with structured-first/string-fallback, exponential backoff with full jitter, frozen typed metadata, safety-critical fallback blocking. This is good engineering. But there's one real bug (`resume` leaking into retries) that will bite you in production when a daemon retries a resumed phase after 529. The other findings are code quality — triple evaluation of the same predicate, inconsistent pattern matching between two sibling functions, and a `for/else` that exists to handle a validated-impossible case. Fix the `resume` bug and clean up the redundant `_is_transient_error` calls; the rest can be addressed at your discretion.