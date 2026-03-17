Now I have a comprehensive understanding of the project. Let me review what's been built, what's been proposed, and identify the biggest gap.

**Features already built:**
1. Core pipeline: CEO → Plan → Implement → Review/Fix Loop → Decision Gate → Deliver
2. Persona packs + interactive init + quick setup
3. Parallel per-persona reviews with dedicated fix agent
4. CEO autonomous proposals with `colonyos auto`
5. Resume failed runs (`--resume`)
6. Rich streaming terminal UI (`-v`, `-q`)
7. Standalone `colonyos review <branch>` command
8. Long-running auto loops with budget/time caps + loop resumption
9. Welcome banner, doctor checks, status command

**Previous CEO proposals (all implemented):**
- Review-driven fix loop ✅
- Resume failed runs ✅
- Standalone review command ✅

Here is my proposal:

---

## Proposal: Post-Implement Verification Gate with Test Command

### Rationale
The pipeline has a critical quality gap between the Implement and Review phases. Currently, code goes straight from implementation to expensive parallel persona reviews without any automated verification that it actually works. If the implement agent produces code with test failures, syntax errors, or broken imports, all reviewer personas waste budget analyzing broken code, and the fix loop must untangle test failures mixed with design feedback. Adding a lightweight verification step that runs the project's test suite before review would catch basic failures early, save significant budget on multi-persona reviews, and let the review/fix loop focus on higher-order quality concerns like design and architecture.

### Feature Request
Add a configurable post-implement verification gate that runs the project's test command after the implement phase. If verification fails, retry the implement phase with the failure output as context (up to a configurable number of retries) before proceeding to review. This creates a fast, cheap inner loop (implement → verify → retry) that catches basic failures before the expensive outer loop (review → fix → re-review).

**Specific requirements:**

1. **New config fields**: Add `verify_command` (string, e.g. `"pytest"`, `"npm test"`, `"make test"`, default: `null`/empty — meaning skip verification) and `max_verify_retries` (int, default: 2) to `.colonyos/config.yaml` under a `verification:` section. When `verify_command` is null/empty, the verification gate is skipped entirely (backward compatible).

2. **New `Phase.VERIFY` enum**: Add a `VERIFY` value to the `Phase` enum so verification attempts are tracked distinctly in the run log, separate from implement and review phases.

3. **Verification execution**: After the implement phase succeeds, if `verify_command` is configured, run the command via `subprocess` in the repo root. Capture stdout/stderr and exit code. If exit code is 0, proceed to review. If non-zero, enter the retry loop.

4. **Implement retry with failure context**: When verification fails, create a new implement phase prompt that includes: (a) the original PRD and task list, (b) the full test failure output (truncated to 4000 chars if needed), and (c) explicit instructions to fix the failing tests on the existing branch without rewriting from scratch. Use a new instruction template `src/colonyos/instructions/verify_fix.md`.

5. **Retry budget**: Each verification retry uses the `per_phase` budget. The total cost of verify + retries is tracked in the run log. If the per-run budget would be exceeded, stop retrying and proceed to review with whatever state exists (let reviewers catch remaining issues).

6. **Pipeline integration**: Wire the verification gate into `orchestrator.run()` between the implement phase and the review/fix loop. The flow becomes: Plan → Implement → **Verify (retry loop)** → Review/Fix → Decision → Deliver. When resuming a failed run, the verify phase should be re-runnable.

7. **CLI output**: Show verification status in the streaming UI — phase header "Verify", test command being run, pass/fail result. On failure: show truncated error output and "Retrying implement (attempt 2/3)..." messages.

8. **`colonyos init` integration**: During `colonyos init`, ask "What command runs your test suite? (leave blank to skip)" and save to config. For `--quick` mode, auto-detect by checking for `pytest.ini`/`pyproject.toml` (pytest), `package.json` (npm test), or `Makefile` (make test).

9. **Tests**: Add unit tests for: config parsing of `verify_command` and `max_verify_retries`, verify phase execution (mock subprocess), retry loop logic (mock phases), budget enforcement during retries, and `colonyos init` test command detection.

**Acceptance criteria:**
- `verify_command: "pytest"` in config causes `pytest` to run after implement phase
- Test failures trigger automatic implement retry with failure context
- Retries are capped by `max_verify_retries` (default 2)
- Each verify attempt appears as a `VERIFY` phase in the run log
- When `verify_command` is empty/null, the gate is skipped (100% backward compatible)
- Budget is enforced across verify retries
- `colonyos init` prompts for test command
- All existing tests continue to pass
- New tests cover config parsing, verify execution, retry logic, budget enforcement, and init integration