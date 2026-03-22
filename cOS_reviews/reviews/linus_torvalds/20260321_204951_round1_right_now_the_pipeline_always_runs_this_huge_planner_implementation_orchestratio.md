# Review by Linus Torvalds (Round 1)

Now let me write the review. I have enough information.

---

## Review: Intent Router Agent — Linus Torvalds

I've read the PRD, the full diff (2,579 lines across 15 files), run the tests (225 passed), and examined the core data structures and control flow.

### The Good

The data structures are right. `RouterCategory` is a simple enum, `RouterResult` is a frozen dataclass with exactly the fields it needs — no inheritance hierarchy, no abstract base classes, no factory patterns. This is how you design things: figure out the data structure first, and the code follows.

The `route_query()` function is clean. Single responsibility: build prompt, call LLM, parse result. No side effects. The fail-open pattern (parse failure → `CODE_CHANGE` with confidence 0.0) is exactly right — when you don't know what to do, do the safe thing.

The `_parse_router_response()` handles real-world garbage well: markdown fences, invalid categories, missing fields, unparseable JSON. This is code written by someone who's dealt with LLMs before.

The Slack integration is well done. The backward-compatible mapping from `RouterResult` → `TriageResult` is clean, and keeping `_triage_message_legacy()` as fallback when `triage_scope` is set is the right call.

### The Problems

**1. `log_router_decision()` calls `datetime.now(timezone.utc)` twice** (lines 404 and 410 in router.py). The filename timestamp and the JSON body timestamp will differ by microseconds. This is sloppy. Capture it once:

```python
now = datetime.now(timezone.utc)
timestamp = now.strftime("%Y%m%d_%H%M%S")
...
"timestamp": now.isoformat(),
```

Not a blocker, but it's the kind of thing that'll confuse someone debugging at 2am.

**2. Massive code duplication between REPL and `run()` routing.** Lines 413-481 in the REPL and lines 668-747 in `run()` are *nearly identical* — same routing call, same category branching, same user-facing messages. This is ~130 lines of duplicated logic. Factor it into a helper function. Something like:

```python
def _handle_routed_query(prompt, config, repo_root, source, quiet=False) -> bool:
    """Returns True if the query was handled (non-pipeline), False to proceed to pipeline."""
```

Then both call sites become 5 lines instead of 35.

**3. Incomplete tasks.** The task file shows tasks 6.1, 7.1, 10.1, 10.2, and 10.3 as incomplete. That's integration tests for `run()`, integration tests for REPL, README docs, and end-to-end tests. The *unit* tests are solid (878 lines in test_router.py), but the integration test gaps are concerning — the two most complex pieces of the implementation (the CLI and REPL integration) have zero integration tests.

**4. `result.artifacts` access pattern is fragile.** In both `route_query()` (line 245-246) and `answer_question()` (line 363-364):

```python
raw_text = next(iter(result.artifacts.values()), "")
```

This grabs whichever value happens to come first from the dict. If `run_phase_sync` ever returns multiple artifacts, this silently grabs the wrong one. It works today, but it's a landmine. At minimum, add a comment explaining *why* this is safe.

**5. The config test change is suspicious.** In `test_config.py`, `test_returns_defaults_when_no_config` changed the assertion from `config.model == "sonnet"` to `config.model == "opus"`. This looks like a side effect of the user direction to "default to opus for all phases" that was snuck into this PR. This is an unrelated change and should be a separate commit.

### Minor Nits

- The `qa_model` field in `RouterConfig` adds a second model knob beyond the PRD spec (PRD only mentions `model` for classification). Fine by me — it's useful — but note it's scope creep.
- The `_QA_TEMPLATE_PATH` fallback (lines 283-292) is good defensive coding.
- 225 tests pass, no regressions. Good.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/router.py]: `log_router_decision()` calls `datetime.now(timezone.utc)` twice, creating a subtle timestamp mismatch between filename and JSON body
- [src/colonyos/cli.py]: ~130 lines of routing logic duplicated between REPL (lines 413-481) and `run()` command (lines 668-747) — extract a shared helper
- [src/colonyos/cli.py]: Integration tests for routing in `run()` and REPL are missing (tasks 6.1, 7.1 still unchecked)
- [src/colonyos/router.py]: `next(iter(result.artifacts.values()), "")` is fragile — relies on dict ordering and single-artifact assumption without documentation
- [tests/test_config.py]: Unrelated change from "sonnet" to "opus" default assertion snuck into this PR

SYNTHESIS:
The core architecture is solid — clean data structures, correct fail-open behavior, good separation between classification and execution, thorough unit tests. But the implementation has two real problems: the routing logic is copy-pasted between REPL and CLI (which is how bugs get introduced when someone fixes one path but not the other), and the integration tests for the two most critical code paths are missing entirely. Fix the duplication and add the integration tests. The timestamp bug and artifacts pattern are minor — fix them while you're in there but they aren't blockers on their own.